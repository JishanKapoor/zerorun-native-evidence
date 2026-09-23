"""Separately frozen real native timeout/termination distinction."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get("ZERORUN_TEST_PACKAGE", "/package"))
from zerorun_harness.api import digest
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness.telemetry import capture_native


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def run(design_path, prepared, qualification_path, root, output):
    output.mkdir(exist_ok=False)
    design = json.loads(design_path.read_text())
    assert design["sha256"] == digest({k: v for k, v in design.items() if k != "sha256"})
    for filename, checksum in design["scripts"].items():
        assert hashlib.sha256((HERE / filename).read_bytes()).hexdigest() == checksum
    save(output / "design.json", design)
    profile = json.loads((prepared / "profile.json").read_text())
    binding = json.loads((prepared / "binding.json").read_text())
    base = json.loads(qualification_path.read_text())
    assert binding["sha256"] == design["binding_sha256"]
    assert base["sha256"] == design["qualification_sha256"]
    case_input = design["case"]
    reference_path = output / "native-reference.json"
    started = time.monotonic()
    native = subprocess.run([sys.executable, "-I", str(HERE / "interruption_reference.py"), str(root), str(prepared), str(design_path), str(reference_path)], capture_output=True, timeout=20)
    (output / "reference.stdout.txt").write_bytes(native.stdout)
    (output / "reference.stderr.txt").write_bytes(native.stderr)
    save(output / "reference-receipt.json", dict(returncode=native.returncode, elapsed_seconds=time.monotonic() - started, authored_native_bank_calls=1))
    assert native.returncode == 0, native.stderr.decode()
    reference = json.loads(reference_path.read_text())
    assert reference["parent"] == {"grade": "timeout", "details": []}
    assert reference["framework_semantics_imported"] is False
    argument = dict(prepared=str(prepared), native_root=str(root), case=case_input, mode="parent")
    parent = capture_native(str(HERE / "adapter.py"), design["scripts"]["adapter.py"], argument, wall_seconds=15)
    save(output / "observed-parent.json", parent)
    assert parent["health"]["native_complete"] and parent["health"]["transport_intact"]
    assert parent["native"]["returned"] == reference["parent"]
    parent_events = [e["event"] for e in parent["transport"]["events"]]
    control = dict(id="native-external-deadline-parent", site="parent-return", role="positive", reference=dict(source_sha256=design["scripts"]["interruption_reference.py"], recipe_sha256=design["sha256"], output_sha256=digest(reference["facts"]), native_source_sha256=digest(binding["original_sources"]), framework_semantics_imported=False, facts=reference["facts"]), observed=parent_events)
    qualification = qualify(profile, binding, base["controls"] + [control])
    save(output / "qualification.json", qualification)
    assert all(qualification["sites"].values())
    argument["mode"] = "worker"
    worker = capture_native(str(HERE / "interruption_adapter.py"), design["scripts"]["interruption_adapter.py"], argument, wall_seconds=2)
    save(output / "interrupted-worker.json", worker)
    assert worker["status"] == "INCOMPLETE" and worker["outer_timeout"]
    assert worker["health"]["native_complete"] is False and worker["health"]["transport_intact"] is False
    assert any(e["event"].get("probe") == "actual_native_unsafe_execute_entry" for e in worker["transport"]["events"])
    typed_worker_events = [e["event"] for e in worker["transport"]["events"] if "site" in e["event"]]
    case = dict(id="native-external-interruption", version="1", inventory=[dict(run="exposed-native-worker", candidate=case_input["id"], obligation=0, phase="base", attempt=1)], source_sha256=digest(binding["original_sources"]), input_sha256=digest(case_input))
    health = dict(binding_sha256=binding["sha256"], sites=qualification["sites"], qualification_sha256=qualification["sha256"], transport={str(parent["producer_pid"]): True, str(worker["producer_pid"]): False}, native_complete={r["id"]: False for r in profile["rules"]})
    result = evaluate(profile, case, typed_worker_events + parent_events, health, binding["sha256"])
    save(output / "audit.json", result)
    assert result["counts"] == {"INCONCLUSIVE": 4}
    save(output / "summary.json", dict(all_passed=True, original_parent=reference["parent"], observed_parent=parent["native"]["returned"], direct_worker_entered=True, direct_worker_terminated_by_outer_deadline=True, absence_accusations=0, counts=result["counts"], authored_native_bank_calls=3, primary_candidate_bank_calls=0, original_and_observed_parent_separate_executions=True))
    print("Native external interruption control passed: 3 calls, 4 INCONCLUSIVE relationships, no absence accusation", flush=True)


if __name__ == "__main__":
    run(*(Path(argument) for argument in sys.argv[1:]))
