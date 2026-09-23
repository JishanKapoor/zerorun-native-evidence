# SPDX-License-Identifier: MIT
"""A4's bounded acquisition transport; domain binding/coverage is a separate duty."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .api import InvalidEvidence, canonical, fingerprint
from ._telemetry_protocol import (
    MAX_TRACE,
    MAX_FRAME,
    VERSION,
    PrimitiveError,
    primitives,
)


def capture_native(
    adapter,
    adapter_sha256,
    argument,
    *,
    start_method="fork",
    wall_seconds=10,
    max_trace_bytes=MAX_TRACE,
):
    """Run a trusted source-pinned adapter in a fresh isolated-mode supervisor.

    The adapter's run(emitter, argument) returns a bounded primitive native value.
    This creates processes, not a security sandbox; use an isolated container for
    untrusted native code. Its stdout/stderr pass through unchanged.
    """
    if (
        type(start_method) is not str
        or start_method != "fork"
        or sys.platform != "linux"
        or sys.flags.optimize != 0
        or sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 11, 16)
    ):
        return dict(
            schema="zerorun-telemetry-capture/1",
            status="UNSUPPORTED",
            reason="qualified acquisition runtime is Linux CPython 3.11.16, fork, optimize=0",
        )
    if type(wall_seconds) not in (int, float) or not 0 < wall_seconds <= 60:
        raise InvalidEvidence(
            "Native wall budget must be positive and at most 60 seconds"
        )
    if (
        type(max_trace_bytes) is not int
        or not MAX_FRAME <= max_trace_bytes <= MAX_TRACE
    ):
        raise InvalidEvidence("Trace byte budget outside supported bounds")
    canonical(argument)
    try:
        primitives(argument)
    except PrimitiveError as exc:
        raise InvalidEvidence(str(exc)) from exc
    path = Path(adapter).resolve()
    if (
        not fingerprint(adapter_sha256)
        or path.stat().st_size > 1024 * 1024
        or hashlib.sha256(path.read_bytes()).hexdigest() != adapter_sha256
    ):
        raise InvalidEvidence("Native adapter source identity/size mismatch")
    request = dict(
        adapter=str(path),
        adapter_sha256=adapter_sha256,
        argument=argument,
        start_method=start_method,
        wall_seconds=wall_seconds,
        max_trace_bytes=max_trace_bytes,
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        inp = folder / "request.json"
        out = folder / "result.json"
        inp.write_bytes(canonical(request))
        package_root = str(Path(__file__).resolve().parents[1])
        bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('zerorun_harness._telemetry_supervisor',run_name='__main__')"
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", bootstrap, package_root, str(inp), str(out)],
            start_new_session=True,
        )
        try:
            code = proc.wait(timeout=wall_seconds + 15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return dict(
                schema="zerorun-telemetry-capture/1",
                status="INCOMPLETE",
                reason="supervisor_deadline",
                health=dict(
                    native_complete=False,
                    transport_intact=False,
                    semantic_coverage=None,
                ),
            )
        if code != 0 or not out.is_file():
            return dict(
                schema="zerorun-telemetry-capture/1",
                status="INCOMPLETE",
                reason="supervisor_failure",
                health=dict(
                    native_complete=False,
                    transport_intact=False,
                    semantic_coverage=None,
                ),
            )
        if out.stat().st_size > 2 * MAX_TRACE:
            raise InvalidEvidence("Supervisor receipt exceeds bound")
        receipt = json.loads(out.read_bytes())
        receipt["caller_pid"] = os.getpid()
        receipt["protocol_version"] = VERSION
        receipt["transport_implementation_sha256"] = {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in [
                "telemetry.py",
                "_telemetry_protocol.py",
                "_telemetry_supervisor.py",
            ]
        }
        return receipt
