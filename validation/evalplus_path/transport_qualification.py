"""Execute a sealed bounded transport inventory in the qualified Linux image."""

import hashlib
import json
from pathlib import Path
import sys
import time

from zerorun_harness._telemetry_multiprocess import capture_native_pair

PROCESS_CONTROLS = [
    {"id": "normal", "status": "CAPTURED", "parent_complete": True, "worker_complete": True, "exitcode": 0},
    {"id": "raise", "status": "CAPTURED", "parent_complete": True, "worker_complete": False, "exitcode": 1},
    {"id": "abrupt", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": False, "exitcode": 0},
    {"id": "killed", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": False, "exitcode": -9},
    {"id": "closed-worker-channel", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": True, "exitcode": 0},
    {"id": "flood", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": True, "exitcode": 0},
    {"id": "extra-child", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": True, "exitcode": 0},
    {"id": "preflight", "status": "INCOMPLETE", "parent_complete": False, "worker_complete": False, "exitcode": None},
    {"id": "buffer-positive", "status": "CAPTURED", "parent_complete": True, "worker_complete": True, "exitcode": 0},
    {"id": "buffer-mismatch", "status": "INCOMPLETE", "parent_complete": True, "worker_complete": True, "exitcode": 0},
]
FAILURE_CONTROLS = [
    {"id": "supervisor-" + mode, "fault": mode, "status": "INCOMPLETE"}
    for mode in ("killed", "nonzero", "missing", "invalid", "before-setsid", "dead-leader")
]
CONTROLS = PROCESS_CONTROLS + FAILURE_CONTROLS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(design, output):
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(design.read_text())
    adapter = Path(__file__).with_name("transport_adapter.py")
    import zerorun_harness._telemetry_multiprocess as transport
    assert frozen["adapter_sha256"] == sha(adapter)
    assert frozen["transport_sha256"] == sha(transport.__file__)
    assert frozen["qualification_sha256"] == sha(__file__)
    assert frozen["fault_supervisor_sha256"] == sha(Path(__file__).with_name("fault_supervisor.py"))
    assert frozen["controls"] == CONTROLS
    for name, expected in frozen["package_sources"].items():
        assert sha(Path(transport.__file__).resolve().parent.parent / name) == expected
    rows = []
    for control in PROCESS_CONTROLS:
        ident = control["id"]
        receipt = capture_native_pair(
            adapter, sha(adapter), {"mode": ident},
            wall_seconds=8, max_trace_bytes=8192 if ident == "flood" else 1048576,
        )
        (output / (ident + ".json")).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        checks = {
            "status": receipt.get("status") == control["status"],
            "parent_complete": receipt.get("lifecycle", {}).get("parent", {}).get("complete") == control["parent_complete"],
            "worker_complete": receipt.get("lifecycle", {}).get("worker", {}).get("complete") == control["worker_complete"],
        }
        if ident == "preflight":
            checks["zero_child"] = not receipt["graph"]["worker_required"]
            checks["native_exception"] = receipt["native"]["exception"] == "TypeError"
        else:
            checks["native_exitcode"] = receipt["native"]["returned"]["first_child_exitcode"] == control["exitcode"]
        if ident == "normal":
            pids = receipt["graph"]
            checks["distinct_pids"] = pids["parent_pid"] != pids["worker_pid"]
            checks["matched_native_child"] = pids["worker_pid"] == pids["expected_worker_pid"]
            checks["each_sealed"] = all(len(t["seals"]) == 1 for t in receipt["transport"].values())
            checks["correct_producers"] = all(
                all(packet["producer"] == pids[role + "_pid"] for packet in t["events"])
                for role, t in receipt["transport"].items()
            )
        if ident in ("buffer-positive", "buffer-mismatch"):
            checks["buffer_linkage"] = receipt["graph"]["buffers"]["matched"] is (ident == "buffer-positive")
        rows.append({"control": ident, "checks": checks, "passed": all(checks.values())})
    for control in FAILURE_CONTROLS:
        ident, mode = control["id"], control["fault"]
        proof_path = output / (ident + "-raw-process-proof.json")
        original_popen = transport.subprocess.Popen

        def fault_popen(command, **kwargs):
            # Only this test replaces the supervisor bootstrap. The public
            # capture wrapper and its failure cleanup execute unchanged.
            replacement = [
                command[0], "-I", str(Path(__file__).with_name("fault_supervisor.py")),
                command[-3], command[-2], command[-1], mode, str(proof_path),
            ]
            return original_popen(replacement, **kwargs)

        transport.subprocess.Popen = fault_popen
        try:
            receipt = capture_native_pair(
                adapter, sha(adapter), {"mode": "killed"}, wall_seconds=8,
            )
        finally:
            transport.subprocess.Popen = original_popen
        (output / (ident + ".json")).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        proof = json.loads(proof_path.read_text())

        def running(pid):
            path = Path("/proc") / str(pid) / "stat"
            try:
                state = path.read_text().rsplit(")", 1)[1].split()[0]
                return state not in ("Z", "X")
            except FileNotFoundError:
                return False

        deadline = time.monotonic() + 1
        while any(running(proof[key]) for key in ("parent_pid", "worker_pid") if proof[key]) and time.monotonic() < deadline:
            time.sleep(0.01)
        checks = {
            "status": receipt["status"] == control["status"],
            "native_child_really_entered": proof["worker_entered"] if mode != "before-setsid" else proof["barrier_entered"],
            "recorded_native_group_targeted": receipt["failure_cleanup"]["group_pid"] == proof["parent_pid"],
            "parent_terminated": not running(proof["parent_pid"]),
            "worker_terminated": not running(proof["worker_pid"]) if proof["worker_pid"] else True,
        }
        if mode == "before-setsid":
            checks["actual_before_setsid_barrier"] = proof["native_parent_group"] == proof["supervisor_pid"] != proof["parent_pid"]
            checks["matching_kernel_identity"] = receipt["failure_cleanup"]["recorded_starttime"] == proof["kernel_starttime"]
            checks["verified_direct_pid_fallback"] = receipt["failure_cleanup"]["direct_pid_fallback"] == "matching_owned_PID_SIGKILL"
        if mode == "dead-leader":
            checks['leader_reaped_before_supervisor_failure'] = proof['leader_reaped']
            checks['descendant_survived_original_leader'] = proof['worker_survived_leader']
            checks['remaining_group_signalled'] = receipt['failure_cleanup']['action'] == 'SIGKILL'
        rows.append({"control": ident, "checks": checks, "passed": all(checks.values())})
    result = {"schema": "s8-pair-transport-qualification/1", "controls": rows,
              "passed": all(row["passed"] for row in rows),
              "native_evalplus_bank_calls": 0, "authored_process_controls": len(rows),
              "scope": "Transport/lifecycle controls only; not semantic site qualification"}
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    report = run(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
