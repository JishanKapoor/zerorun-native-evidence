"""Execute frozen exposed internal-source controls and retain every native route."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, os.environ.get("ZERORUN_TEST_PACKAGE", "/package"))
from evalplus_internal.controls import identity
from zerorun_harness.api import digest
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness.telemetry import capture_native


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def run(prepared, output, native_sources, ordinary_path):
    output.mkdir(parents=True, exist_ok=False)
    design = json.loads((prepared / "design.json").read_text())
    assert digest({k: v for k, v in design.items() if k != "sha256"}) == design["sha256"]
    assert hashlib.sha256((HERE / "reference.py").read_bytes()).hexdigest() == design["reference_recipe_sha256"]
    save(output / "sealed-design.json", design)
    spec = importlib.util.spec_from_file_location("ordinary_relationships", ordinary_path)
    ordinary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ordinary)
    ledger = []
    rows = []
    qualifications = []
    adapter_sha = hashlib.sha256((HERE / "adapter.py").read_bytes()).hexdigest()

    def receipt(row):
        ledger.append(row)
        with (output / "native-call-ledger.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    for source in design["controls"]:
        label = source["id"]
        prepared_source = prepared / label
        folder = output / label
        folder.mkdir()
        profile = json.loads((prepared_source / "profile.json").read_text())
        binding = json.loads((prepared_source / "binding.json").read_text())
        cases = json.loads((prepared_source / "controls.json").read_text())
        assert digest(profile) == source["profile_sha256"] and digest(cases) == source["controls_sha256"]
        assert binding["sha256"] == source["binding_sha256"]
        controls, executions = [], []
        native_root = native_sources / source["source_revision"]
        for case in cases + [json.loads((prepared_source / "parent-negative.json").read_text())]:
            ident = case["id"]
            case_path = folder / (ident + "-input.json")
            save(case_path, case)
            ref_path = folder / (ident + "-reference.json")
            started = time.monotonic()
            completed = subprocess.run([sys.executable, "-I", str(HERE / "reference.py"), str(native_root), str(case_path), str(ref_path), str(prepared_source / "native.py")], capture_output=True, timeout=30)
            (folder / (ident + "-reference.stdout.txt")).write_bytes(completed.stdout)
            (folder / (ident + "-reference.stderr.txt")).write_bytes(completed.stderr)
            receipt(dict(source=label, control=ident, route="unmodified-reference-worker-and-parent", planned_authored_bank_calls=0 if case.get("preflight_error") else 2, returncode=completed.returncode, elapsed_seconds=time.monotonic() - started))
            assert completed.returncode == 0, (label, ident, completed.stderr.decode())
            reference = json.loads(ref_path.read_text())
            assert reference["framework_semantics_imported"] is False
            events, captures = [], {}
            for mode in (["parent"] if case.get("preflight_error") else ["worker", "parent"]):
                started = time.monotonic()
                capture = capture_native(str(HERE / "adapter.py"), adapter_sha, dict(prepared=str(prepared_source), native_root=str(native_root), case=case, mode=mode), wall_seconds=15)
                captures[mode] = capture
                save(folder / (ident + "-" + mode + "-capture.json"), capture)
                receipt(dict(source=label, control=ident, route="observed-" + mode, planned_authored_bank_calls=0 if case.get("preflight_error") else 1, status=capture["status"], elapsed_seconds=time.monotonic() - started))
                assert capture["health"]["transport_intact"] is True, (label, ident, mode, capture)
                observed_events = [packet["event"] for packet in capture["transport"]["events"]]
                events.extend(observed_events)
                if case.get("preflight_error"):
                    assert capture["native"]["exception"] == "TypeError"
                    assert not observed_events
                else:
                    assert capture["health"]["native_complete"] is True, (label, ident, mode, capture)
                    assert capture["native"]["returned"] == reference[mode], (label, ident, mode, capture["native"]["returned"], reference[mode])
            for site in (["parent-return"] if case.get("preflight_error") else profile["sites"]):
                expected = reference["facts"][site]
                observed = [e for e in events if e["site"] == site]
                controls.append(dict(id=ident + ":" + site, site=site, role="positive" if expected else "negative", reference=dict(source_sha256=hashlib.sha256((HERE / "reference.py").read_bytes()).hexdigest(), recipe_sha256=digest(dict(case=case, source=source["native_sha256"], route="independent original native line transitions and raw values")), output_sha256=digest(expected), native_source_sha256=digest(binding["original_sources"]), framework_semantics_imported=False, facts=expected), observed=observed))
            if not case.get("preflight_error"):
                executions.append((case, reference, events, captures))
            print(label + " / " + ident + ": native outcomes retained", flush=True)
        certificate = qualify(profile, binding, controls)
        save(folder / "qualification.json", certificate)
        assert all(certificate["sites"].values()), (label, certificate["sites"], [c for c in certificate["checks"] if not c["passed"]])
        qualifications.append(dict(source=label, sites=len(certificate["sites"]), checks=len(certificate["checks"]), all_passed=all(c["passed"] for c in certificate["checks"]), sha256=certificate["sha256"]))
        for case_input, reference, events, captures in executions:
            ident = case_input["id"]
            case = dict(id=label + ":" + ident, version="1", inventory=[identity(i, case_input) for i in range(len(case_input["inputs"]))], source_sha256=digest(binding["original_sources"]), input_sha256=digest(case_input))
            health = dict(binding_sha256=binding["sha256"], sites=certificate["sites"], qualification_sha256=certificate["sha256"], transport={str(c["producer_pid"]): c["health"]["transport_intact"] for c in captures.values()}, native_complete={r["id"]: all(c["health"]["native_complete"] for c in captures.values()) for r in profile["rules"]})
            result = evaluate(profile, case, events, health, binding["sha256"])
            # Keep the ordinary implementation separate from the production monitor.
            actual = [(r["relationship"], tuple(r["identity"].values()), r["status"]) for r in result["records"]]
            assert actual == ordinary.run(profile, case, events, health)
            # Independent raw reference determines required physical write presence.
            native_decisions = reference["facts"]["accept-exact"] + reference["facts"]["accept-tolerant"] + reference["facts"]["accept-polynomial"] + reference["facts"]["caught-rejection"]
            for relationship, sites in [("decision-requires-detail", ["true-commit", "false-commit"]), ("decision-requires-progress", ["progress-write"])]:
                witnesses = {f["identity"]["obligation"] for f in native_decisions}
                writes = {f["identity"]["obligation"] for site in sites for f in reference["facts"][site]}
                for record in result["records"]:
                    if record["relationship"] == relationship:
                        i = record["identity"]["obligation"]
                        assert record["status"] == ("VIOLATION" if i in witnesses - writes else "CONFORMS")
            if label == "before" and ident == "polynomial-accepted-continue":
                assert result["counts"].get("VIOLATION") == 2
            if label == "after" and ident == "polynomial-accepted-continue":
                assert result["counts"] == {"CONFORMS": 4}
            if ident == "legitimate-pre-decision-skip":
                assert result["counts"].get("VIOLATION", 0) == 0
            if ident == "rejected-continuation":
                assert reference["worker"]["stat"] == 0 and reference["parent"]["grade"] == "fail"
            stem = folder / ident
            save(Path(str(stem) + "-audit.json"), result)
            save(Path(str(stem) + "-events.json"), events)
            save(Path(str(stem) + "-case.json"), case)
            save(Path(str(stem) + "-health.json"), health)
            rows.append(dict(source=label, control=ident, counts=result["counts"], native_unchanged=True, independent_reference_matches=True, ordinary_matches=True, reference_exceptions=reference["exceptions"], raw_worker=reference["worker"], raw_parent=reference["parent"], direct_worker_and_parent_are_separate_executions=True))
        # Physical callbacks above qualify these sites. Counterfactual corruption
        # below tests qualification refusal and executes no additional candidates.
        bad = copy.deepcopy(controls)
        affected = next(c for c in bad if c["site"] == "accept-exact" and c["role"] == "positive")
        affected["observed"] = []
        missing = qualify(profile, binding, bad)
        assert missing["sites"]["accept-exact"] is False
        save(folder / "missing-observer-qualification.json", missing)
    summary = dict(schema="evalplus-internal-campaign/1", all_passed=True, control_count=len(rows), source_realizations=len(design["controls"]), qualifications=qualifications, cases=rows, authored_native_bank_calls=sum(r["planned_authored_bank_calls"] for r in ledger), primary_candidate_bank_calls=0, canonical_bank_calls=0, same_execution_end_to_end_trace=False, scope="Actual pinned worker and parent native paths qualified in separate executions; exposed source and authored variants only")
    save(output / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ["cases", "qualifications"]}, indent=2), flush=True)


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
