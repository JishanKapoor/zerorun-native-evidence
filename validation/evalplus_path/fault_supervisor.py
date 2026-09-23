"""Sealed test-only supervisor failures after a real native child has entered."""

import json
import os
from pathlib import Path
import signal
import sys
import time

package, request_path, output_path, mode, evidence = sys.argv[1:]
sys.path.insert(0, package)
from zerorun_harness import _telemetry_multiprocess as transport


def fail_after_started(request, state, result, length, proc, pipes, owned, start, fault):
    transport._record_owned_group(request["group_receipt"], proc.pid)
    deadline = time.monotonic() + 3
    while not state["worker_entered"].value and time.monotonic() < deadline:
        time.sleep(0.001)
    snapshot = {
        "mode": mode, "supervisor_pid": os.getpid(), "parent_pid": proc.pid,
        "worker_pid": int(state["worker_pid"].value),
        "worker_entered": bool(state["worker_entered"].value),
    }
    if mode == "dead-leader":
        os.kill(proc.pid,signal.SIGKILL)
        proc.join(2)
        snapshot['leader_reaped'] = proc.exitcode == -signal.SIGKILL and transport._linux_process_identity(proc.pid) is None
        snapshot['worker_survived_leader'] = transport._linux_process_identity(snapshot['worker_pid']) is not None
    with Path(evidence).open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream)
    if mode == "invalid":
        Path(output_path).write_text("{deliberately invalid")
        os._exit(0)
    if mode == "missing":
        os._exit(0)
    if mode in ("killed","dead-leader"):
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(17)


def barrier_parent(reads, writes, request, state, result, length):
    # Deliberately before production _parent and therefore before setsid.
    # This test-only replacement performs no native EvalPlus call.
    state["parent_pid"].value = os.getpid()
    state["parent_setup_error"].value = 1
    while True:
        time.sleep(0.01)


def fail_before_setsid(request, state, result, length, proc, pipes, owned, start, fault):
    transport._record_owned_group(request["group_receipt"], proc.pid)
    deadline = time.monotonic() + 3
    while not state["parent_setup_error"].value and time.monotonic() < deadline:
        time.sleep(0.001)
    with Path(evidence).open("x", encoding="utf-8") as stream:
        json.dump({"mode": mode, "supervisor_pid": os.getpid(), "parent_pid": proc.pid,
                   "worker_pid": None, "worker_entered": False,
                   "barrier_entered": bool(state["parent_setup_error"].value),
                   "native_parent_group": os.getpgid(proc.pid),
                   "kernel_starttime": transport._linux_process_identity(proc.pid)}, stream)
    os.kill(os.getpid(), signal.SIGKILL)


if mode == "before-setsid":
    transport._parent = barrier_parent
    transport._collect_started = fail_before_setsid
else:
    transport._collect_started = fail_after_started
transport.acquire(json.loads(Path(request_path).read_bytes()))
