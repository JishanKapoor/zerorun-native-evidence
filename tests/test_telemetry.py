# SPDX-License-Identifier: MIT
"""Protocol controls with independently constructed wire bytes and expectations."""

import errno
import json
import struct
import zlib
import pytest
from zerorun_harness._telemetry_protocol import (
    Collector,
    Emitter,
    PrimitiveError,
    UnsupportedTransport,
    encode,
    primitives,
)


def frame(packet):
    data = json.dumps(packet, separators=(",", ":")).encode()
    return b"ZR11" + struct.pack("!II", len(data), zlib.crc32(data)) + data


def event(seq=1):
    return dict(
        protocol="zerorun-telemetry/1",
        producer=73,
        type="event",
        seq=seq,
        event={"native": True},
    )


def seal(n=1):
    return dict(
        protocol="zerorun-telemetry/1",
        producer=73,
        type="seal",
        attempted=n,
        emitted=n,
        dropped=0,
        rejected=0,
        partial=0,
    )


@pytest.mark.parametrize("chunk", [1, 2, 3, 11, 12, 13, 4096])
def test_independent_frame_reconstruction(chunk):
    raw = frame(event()) + frame(seal())
    c = Collector(73)
    for i in range(0, len(raw), chunk):
        c.feed(raw[i : i + chunk])
    result = c.finish()
    assert (
        result["transport_intact"]
        and result["events"] == [event()]
        and result["seals"] == [seal()]
    )


@pytest.mark.parametrize(
    "change",
    [
        "magic",
        "length",
        "checksum",
        "json",
        "truncated",
        "missing_seal",
        "duplicate",
        "after_seal",
        "wrong_pid",
        "boolean_seq",
    ],
)
def test_faults_cannot_qualify(change):
    raw = frame(event()) + frame(seal())
    if change == "magic":
        raw = b"NOPE" + raw[4:]
    elif change == "length":
        raw = raw[:4] + struct.pack("!I", 5000) + raw[8:]
    elif change == "checksum":
        raw = raw[:8] + bytes([raw[8] ^ 1]) + raw[9:]
    elif change == "json":
        data = b"notjson"
        raw = b"ZR11" + struct.pack("!II", len(data), zlib.crc32(data)) + data
    elif change == "truncated":
        raw = raw[:-1]
    elif change == "missing_seal":
        raw = frame(event())
    elif change == "duplicate":
        raw = frame(event()) + frame(event()) + frame(seal(2))
    elif change == "after_seal":
        raw = frame(event()) + frame(seal()) + frame(event(2))
    elif change == "wrong_pid":
        p = event()
        p["producer"] = 74
        raw = frame(p) + frame(seal())
    elif change == "boolean_seq":
        p = event()
        p["seq"] = True
        raw = frame(p) + frame(seal())
    c = Collector(73)
    c.feed(raw)
    assert c.finish()["transport_intact"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempted", 2),
        ("emitted", 0),
        ("dropped", 1),
        ("rejected", 1),
        ("partial", 1),
        ("attempted", True),
        ("emitted", -1),
    ],
)
def test_seal_accounting(field, value):
    s = seal()
    s[field] = value
    c = Collector(73)
    c.feed(frame(event()) + frame(s))
    assert not c.finish()["transport_intact"]


def test_trace_cap_stops_storage_but_counts_received_bytes():
    c = Collector(73, 4096)
    for i in range(100):
        c.feed(frame(event(i + 1)))
    count = len(c.events)
    c.feed(b"x" * 100000)
    assert (
        len(c.events) == count
        and not c.buffer
        and c.received > 100000
        and "trace_cap" in c.finish()["errors"]
    )


@pytest.fixture
def emitter(monkeypatch):
    import os

    monkeypatch.setattr(os, "get_blocking", lambda fd: False)
    monkeypatch.setattr(os, "fpathconf", lambda fd, key: 4096, raising=False)
    return Emitter(-1)


def test_emitter_wire_bytes_and_seal(emitter):
    writes = []
    emitter._write = lambda fd, data: writes.append(data) or len(data)
    assert emitter.emit({"number": 4}) and emitter.seal()
    c = Collector(emitter.producer)
    for data in writes:
        c.feed(data)
    r = c.finish()
    assert r["transport_intact"] and r["events"][0]["event"] == {"number": 4}


@pytest.mark.parametrize(
    "number", [errno.EAGAIN, errno.EPIPE, errno.EBADF, errno.EINVAL]
)
def test_transport_oserrors_do_not_escape_native_path(emitter, number):
    def broken(fd, data):
        raise OSError(number, "transport control")

    emitter._write = broken
    assert not emitter.emit({"value": 1}) and not emitter.seal()
    assert (emitter.attempted, emitter.emitted, emitter.dropped) == (1, 0, 1)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        TimeoutError(errno.ETIMEDOUT, "native"),
        InterruptedError(errno.EINTR, "native"),
        KeyboardInterrupt(),
        SystemExit(7),
        RuntimeError("native"),
    ],
)
def test_native_interruptions_propagate(emitter, error):
    def interrupted(fd, data):
        raise error

    emitter._write = interrupted
    with pytest.raises(type(error)) as caught:
        emitter.emit({"value": 1})
    assert caught.value is error


def test_partial_write_is_loss(emitter):
    emitter._write = lambda fd, data: 1
    assert (
        not emitter.emit({"value": 1}) and emitter.partial == 1 and emitter.dropped == 1
    )


@pytest.mark.parametrize(
    "value",
    [
        object(),
        (1,),
        float("nan"),
        float("inf"),
        1 << 200,
        "x" * 1025,
        {1: 2},
        list(range(65)),
    ],
)
def test_unsupported_primitives_are_dropped(emitter, value):
    emitter._write = lambda *a: (_ for _ in ()).throw(AssertionError("must not write"))
    assert not emitter.emit(value) and emitter.rejected == 1 and emitter.dropped == 1


def test_no_candidate_repr_pickle_or_conversion(emitter):
    class Candidate:
        def __repr__(self):
            raise AssertionError("repr called")

        def __str__(self):
            raise AssertionError("str called")

        def __reduce__(self):
            raise AssertionError("pickle called")

        def __iter__(self):
            raise AssertionError("iterator called")

    assert not emitter.emit(Candidate())
    cyclic = []
    cyclic.append(cyclic)
    assert not emitter.emit(cyclic)
    deep = 0
    for _ in range(10):
        deep = [deep]
    with pytest.raises(PrimitiveError):
        primitives(deep)


def test_frame_limit(emitter):
    assert not emitter.emit(["x" * 1024 for _ in range(5)]) and emitter.rejected == 1


def test_event_after_seal_recorded_as_loss(emitter):
    emitter._write = lambda fd, data: len(data)
    assert emitter.seal()
    assert (
        not emitter.emit({"late": True})
        and emitter.attempted == emitter.dropped == emitter.rejected == 1
    )


@pytest.mark.parametrize("limit", [False, 4095, 16777217, 0])
def test_unsupported_limits(limit):
    with pytest.raises(UnsupportedTransport):
        Collector(1, limit)


def test_wire_encoder_matches_independent_frame():
    # Canonical byte ordering is allowed to differ; decode without production Collector.
    raw = encode(event())
    magic, n, crc = struct.unpack("!4sII", raw[:12])
    assert magic == b"ZR11" and n == len(raw) - 12 and crc == zlib.crc32(raw[12:])
    assert json.loads(raw[12:]) == event()


@pytest.mark.parametrize("mode", ["spawn", "forkserver", "unknown", None, False])
def test_unsupported_start_methods_refused_before_adapter_execution(mode):
    from zerorun_harness.telemetry import capture_native

    assert (
        capture_native("never-read.py", "0" * 64, {}, start_method=mode)["status"]
        == "UNSUPPORTED"
    )


def test_failed_descriptor_setup_is_explicit(monkeypatch):
    import os

    def fail(fd):
        raise OSError(errno.EBADF, "setup failed")

    monkeypatch.setattr(os, "get_blocking", fail)
    with pytest.raises(UnsupportedTransport, match="initialization"):
        Emitter(-1)


def test_wrong_pipe_mode_is_unsupported(monkeypatch):
    import os

    monkeypatch.setattr(os, "get_blocking", lambda fd: True)
    with pytest.raises(UnsupportedTransport):
        Emitter(-1)


def test_worker_setup_failure_precedes_native_code(monkeypatch):
    import zerorun_harness._telemetry_supervisor as s

    def fail(fd):
        raise UnsupportedTransport("injected setup failure")

    monkeypatch.setattr(s, "Emitter", fail)
    monkeypatch.setattr(s.os, "close", lambda fd: None)

    class Box:
        value = 0

    output = bytearray(65536)
    length = Box()
    completed = Box()
    s.worker(
        1,
        2,
        b"raise AssertionError('native code must not execute')",
        "native.py",
        {},
        output,
        length,
        completed,
    )
    assert (
        completed.value == 0
        and json.loads(output[: length.value])["setup_error"]
        == "descriptor_initialization"
    )
