# SPDX-License-Identifier: MIT
"""One fresh supervisor and fork producer per trusted acquisition attempt."""

import hashlib
import errno
import json
import multiprocessing as mp
import os
from pathlib import Path
import selectors
import sys
import time

from ._telemetry_protocol import Collector, Emitter, UnsupportedTransport, primitives


def worker(read_fd, write_fd, source, filename, argument, result, length, completed):
    os.close(read_fd)
    close = os.close
    try:
        emitter = Emitter(write_fd)  # pipe and serializer ready before native guard
    except UnsupportedTransport:
        data = b'{"returned":null,"exception":null,"setup_error":"descriptor_initialization"}'
        result[: len(data)] = data
        length.value = len(data)
        try:
            close(write_fd)
        except OSError:
            pass  # No native adapter has been entered.
        return

    def save(value):
        value["telemetry_counts"] = {
            k: getattr(emitter, k)
            for k in ["attempted", "emitted", "dropped", "rejected", "partial"]
        }
        primitives(value)
        data = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(data) > len(result):
            raise UnsupportedTransport("Native result exceeds control-plane bound")
        result[: len(data)] = data
        length.value = len(data)

    try:
        namespace = {
            "__name__": "_zerorun_trusted_native_adapter",
            "__file__": filename,
        }
        exec(compile(source, filename, "exec"), namespace)
        value = namespace["run"](emitter, argument)
        completed.value = 1
        save(
            dict(
                returned=value,
                exception=None,
                telemetry_initialized_before_adapter=True,
            )
        )
    except BaseException as exc:
        # Record only class identity, never candidate repr/str/pickle. Re-raise
        # preserves timeout/termination as process outcomes instead of success.
        save(
            dict(
                returned=None,
                exception=type(exc).__name__,
                telemetry_initialized_before_adapter=True,
            )
        )
        raise
    finally:
        try:
            emitter.seal()
        finally:
            try:
                close(write_fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise


def acquire(request, *, _collector_fault=None):
    if (
        sys.platform != "linux"
        or sys.flags.optimize != 0
        or request["start_method"] != "fork"
        or sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 11, 16)
    ):
        raise UnsupportedTransport("Only Linux CPython 3.11.16 fork optimize=0 is qualified")
    source = Path(request["adapter"]).read_bytes()
    if (
        len(source) > 1024 * 1024
        or hashlib.sha256(source).hexdigest() != request["adapter_sha256"]
    ):
        raise UnsupportedTransport("Adapter source changed before acquisition")
    try:
        rd, wr = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        if os.fpathconf(wr, "PC_PIPE_BUF") < 4096:
            raise UnsupportedTransport("Insufficient atomic pipe size")
    except OSError as exc:
        raise UnsupportedTransport("Descriptor initialization failed") from exc
    ctx = mp.get_context("fork")
    result = ctx.RawArray("B", 65536)
    length = ctx.RawValue("I", 0)
    completed = ctx.RawValue("b", 0)
    proc = ctx.Process(
        target=worker,
        args=(
            rd,
            wr,
            source,
            str(Path(request["adapter"])),
            request["argument"],
            result,
            length,
            completed,
        ),
    )
    start = time.monotonic()
    proc.start()
    os.close(wr)
    collector = Collector(proc.pid, request["max_trace_bytes"])
    selector = selectors.DefaultSelector()
    selector.register(rd, selectors.EVENT_READ)
    timed_out = False
    eof = False
    try:
        if _collector_fault == "broken":
            selector.unregister(rd)
            os.close(rd)
            rd = None
            collector.fail("collector_closed_channel")
        while proc.is_alive() or not eof:
            if time.monotonic() - start >= request["wall_seconds"]:
                timed_out = True
                proc.kill()
                proc.join(3)
                break
            if _collector_fault == "stopped":
                collector.fail("collector_stopped")
                time.sleep(0.002)
                if not proc.is_alive():
                    break
                continue
            if rd is None:
                time.sleep(0.002)
                if not proc.is_alive():
                    break
                continue
            for key, _ in selector.select(0.01):
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if data:
                    collector.feed(data)
                else:
                    eof = True
                    selector.unregister(rd)
                    break
            if eof and not proc.is_alive():
                break
        proc.join(3)
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(3)
        selector.close()
        if rd is not None:
            os.close(rd)
    transport = collector.finish()
    control = json.loads(bytes(result[: length.value])) if length.value else None
    if control and transport["seals"]:
        seal = transport["seals"][0]
        if any(
            control["telemetry_counts"][k] != seal[k]
            for k in control["telemetry_counts"]
        ):
            transport["transport_intact"] = False
            transport["errors"].append("control_plane_counter_disagreement")
    setup_error = bool(control and control.get("setup_error"))
    native_complete = bool(
        completed.value
        and proc.exitcode == 0
        and not timed_out
        and control is not None
        and control["exception"] is None
    )
    status = (
        "UNSUPPORTED"
        if setup_error
        else "CAPTURED"
        if native_complete and transport["transport_intact"]
        else "INCOMPLETE"
    )
    return dict(
        schema="zerorun-telemetry-capture/1",
        status=status,
        supervisor_pid=os.getpid(),
        producer_pid=proc.pid,
        worker_exitcode=proc.exitcode,
        outer_timeout=timed_out,
        native=control,
        transport=transport,
        health=dict(
            native_complete=native_complete,
            transport_intact=transport["transport_intact"],
            semantic_coverage=None,
        ),
        adapter_sha256=request["adapter_sha256"],
        start_method="fork",
        optimize=sys.flags.optimize,
        wall_seconds=time.monotonic() - start,
        scope="Transport qualification only; a seal is not semantic coverage or candidate acceptance",
    )


def main():
    request = json.loads(Path(sys.argv[1]).read_bytes())
    try:
        result = acquire(request)
    except UnsupportedTransport as exc:
        result = dict(
            schema="zerorun-telemetry-capture/1", status="UNSUPPORTED", reason=str(exc)
        )
    with Path(sys.argv[2]).open("x", encoding="utf-8") as f:
        json.dump(result, f, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
