# SPDX-License-Identifier: MIT
"""Finite Linux pipe protocol. Transport integrity never proves semantic coverage."""

import errno
import json
import math
import os
import struct
import zlib

VERSION = "zerorun-telemetry/1"
MAX_FRAME = 4096
MAX_TRACE = 16 * 1024 * 1024
HEADER = struct.Struct("!4sII")
MAGIC = b"ZR11"
TRANSPORT_ERRNOS = {
    errno.EAGAIN,
    errno.EWOULDBLOCK,
    errno.EPIPE,
    errno.EBADF,
    errno.EINVAL,
}


class PrimitiveError(ValueError):
    """An internally detected unsupported telemetry value, not a native exception."""


class UnsupportedTransport(ValueError):
    pass


def primitives(value):
    active = set()
    budget = [4096]

    def visit(v, depth):
        budget[0] -= 1
        if budget[0] < 0 or depth > 8:
            raise PrimitiveError("primitive depth/node cap")
        kind = type(v)
        if v is None or kind is bool:
            return
        if kind is int:
            if v.bit_length() > 128:
                raise PrimitiveError("integer cap")
            return
        if kind is float:
            if not math.isfinite(v):
                raise PrimitiveError("nonfinite value")
            return
        if kind is str:
            if len(v) > 1024 or any(0xD800 <= ord(c) <= 0xDFFF for c in v):
                raise PrimitiveError("string cap/encoding")
            return
        if kind not in (dict, list):
            raise PrimitiveError("not an exact primitive container")
        if id(v) in active:
            raise PrimitiveError("cyclic value")
        if len(v) > (32 if kind is dict else 64):
            raise PrimitiveError("container cap")
        active.add(id(v))
        if kind is dict:
            for key, item in v.items():
                if type(key) is not str:
                    raise PrimitiveError("nonstring key")
                visit(key, depth + 1)
                visit(item, depth + 1)
        else:
            for item in v:
                visit(item, depth + 1)
        active.remove(id(v))

    visit(value, 0)


def encode(packet):
    primitives(packet)
    data = json.dumps(
        packet,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(data) + HEADER.size > MAX_FRAME:
        raise PrimitiveError("frame cap")
    return HEADER.pack(MAGIC, len(data), zlib.crc32(data)) + data


def _pairs(items):
    result = {}
    for k, v in items:
        if k in result:
            raise PrimitiveError("duplicate key")
        result[k] = v
    return result


class Emitter:
    """Construct before entering a native guard; never use native stdout/stderr."""

    def __init__(self, fd):
        try:
            if os.get_blocking(fd) or os.fpathconf(fd, "PC_PIPE_BUF") < MAX_FRAME:
                raise UnsupportedTransport("nonblocking atomic pipe unavailable")
        except (OSError, AttributeError) as exc:
            raise UnsupportedTransport("descriptor initialization failed") from exc
        self.fd = fd
        self.producer = os.getpid()
        self._write = os.write
        self.attempted = self.emitted = self.dropped = self.rejected = self.partial = 0
        self.sealed = False

    def _send(self, packet):
        data = encode(packet)
        try:
            count = self._write(self.fd, data)
        except OSError as exc:
            # Do not swallow native timeout/termination exceptions (including
            # TimeoutError with no errno or ETIMEDOUT). EINTR also propagates.
            if exc.errno not in TRANSPORT_ERRNOS:
                raise
            return False
        if count != len(data):
            self.partial += 1
            return False
        return True

    def emit(self, event):
        self.attempted += 1
        if self.sealed:
            self.dropped += 1
            self.rejected += 1
            return False
        try:
            sent = self._send(
                dict(
                    protocol=VERSION,
                    producer=self.producer,
                    type="event",
                    seq=self.attempted,
                    event=event,
                )
            )
        except PrimitiveError:
            self.rejected += 1
            sent = False
        if sent:
            self.emitted += 1
        else:
            self.dropped += 1
        return sent

    def seal(self):
        if self.sealed:
            return False
        self.sealed = True
        return self._send(
            dict(
                protocol=VERSION,
                producer=self.producer,
                type="seal",
                attempted=self.attempted,
                emitted=self.emitted,
                dropped=self.dropped,
                rejected=self.rejected,
                partial=self.partial,
            )
        )


class Collector:
    """Bounded decoder: malformed/truncated frames invalidate, never resynchronize."""

    def __init__(self, producer, max_bytes=MAX_TRACE):
        if type(max_bytes) is not int or not MAX_FRAME <= max_bytes <= MAX_TRACE:
            raise UnsupportedTransport("trace limit must be 4096..16777216 bytes")
        self.producer = producer
        self.max_bytes = max_bytes
        self.received = 0
        self.buffer = bytearray()
        self.events = []
        self.seals = []
        self.errors = []
        self.invalid = False
        self.after_seal = False

    def fail(self, reason):
        if reason not in self.errors:
            self.errors.append(reason)
        self.invalid = True
        self.buffer.clear()

    def feed(self, data):
        self.received += len(data)
        if self.received > self.max_bytes:
            self.fail("trace_cap")
        if self.invalid:
            return
        self.buffer.extend(data)
        while len(self.buffer) >= HEADER.size:
            magic, n, checksum = HEADER.unpack(self.buffer[: HEADER.size])
            if magic != MAGIC or n == 0 or n > MAX_FRAME - HEADER.size:
                self.fail("invalid_frame_header")
                return
            if len(self.buffer) < HEADER.size + n:
                return
            payload = bytes(self.buffer[HEADER.size : HEADER.size + n])
            del self.buffer[: HEADER.size + n]
            if zlib.crc32(payload) != checksum:
                self.fail("frame_checksum")
                return
            try:
                packet = json.loads(
                    payload.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=lambda x: (_ for _ in ()).throw(
                        PrimitiveError("nonfinite")
                    ),
                )
                primitives(packet)
            except (ValueError, UnicodeError, RecursionError):
                self.fail("invalid_primitive_packet")
                return
            if (
                type(packet) is not dict
                or packet.get("protocol") != VERSION
                or type(packet.get("producer")) is not int
                or packet["producer"] != self.producer
            ):
                self.fail("protocol_or_producer")
                return
            if self.after_seal:
                self.fail("packet_after_seal")
                return
            if packet.get("type") == "event":
                if (
                    set(packet) != {"protocol", "producer", "type", "seq", "event"}
                    or type(packet["seq"]) is not int
                    or packet["seq"] != len(self.events) + 1
                ):
                    self.fail("event_sequence")
                    return
                self.events.append(packet)
            elif packet.get("type") == "seal":
                keys = {
                    "protocol",
                    "producer",
                    "type",
                    "attempted",
                    "emitted",
                    "dropped",
                    "rejected",
                    "partial",
                }
                if set(packet) != keys or any(
                    type(packet[k]) is not int or packet[k] < 0
                    for k in keys - {"protocol", "producer", "type"}
                ):
                    self.fail("invalid_seal")
                    return
                self.seals.append(packet)
                self.after_seal = True
            else:
                self.fail("unknown_packet")
                return

    def finish(self):
        if self.buffer:
            self.fail("partial_frame_at_eof")
        if len(self.seals) != 1:
            self.fail("missing_seal")
        if self.seals:
            s = self.seals[0]
            if (
                s["attempted"],
                s["emitted"],
                s["dropped"],
                s["rejected"],
                s["partial"],
            ) != (len(self.events), len(self.events), 0, 0, 0):
                self.fail("seal_counts_or_loss")
        return dict(
            protocol=VERSION,
            transport_intact=not self.invalid,
            events=self.events,
            seals=self.seals,
            errors=self.errors,
            received_bytes=self.received,
            stored_events=len(self.events),
            limits=dict(max_frame_bytes=MAX_FRAME, max_trace_bytes=self.max_bytes),
        )
