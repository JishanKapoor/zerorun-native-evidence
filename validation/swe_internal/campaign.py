"""Real exposed native parser/grade observations and frozen finite checks.

Run inside the qualified native Linux environment. No arbitrary native expected
grade, production verdict, or observer output is used by the raw reference.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, os.environ.get("ZERORUN_TEST_PACKAGE", "/package"))
from zerorun_harness.api import digest
from zerorun_harness.binding import validate_binding
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness.telemetry import capture_native


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def status(result, relationship, obligation, phase):
    return [row["status"] for row in result["records"] if row["relationship"] == relationship
            and row["identity"]["obligation"] == obligation and row["identity"]["phase"] == phase]


def run(fixture_root, output):
    fixture_root, output = Path(fixture_root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    freeze = json.loads((fixture_root / "freeze.json").read_text())
    cases = json.loads((fixture_root / "cases.json").read_text())
    assert digest(cases) == freeze["case_sha256"]
    cases += [dict(id="no-native-call")]
    all_rows = []
    reference_sha = hashlib.sha256((HERE / "reference.py").read_bytes()).hexdigest()
    recipe_sha = hashlib.sha256((HERE / "native_driver.py").read_bytes()).hexdigest()
    adapter_sha = hashlib.sha256((HERE / "adapter.py").read_bytes()).hexdigest()
    for filename, frozen in freeze["implementation_sha256"].items():
        assert hashlib.sha256((HERE / filename).read_bytes()).hexdigest() == frozen, filename
    calls = {"native_pipeline_invocations": 0, "reference_parser_invocations": 0, "observed_parser_invocations": 0,
             "reference_native_function_calls": 0, "primary_candidate_executions": 0, "authored_log_cases": len(cases) - 1}
    for version in ["before", "after"]:
        profile = json.loads((fixture_root / version / "profile.json").read_text())
        binding = json.loads((fixture_root / version / "binding.json").read_text())
        assert digest(profile) == freeze["versions"][version]["profile_sha256"]
        assert binding["sha256"] == freeze["versions"][version]["binding_sha256"]
        validate_binding(profile, binding)
        controls, retained = [], []
        for case in cases:
            name = version + "-" + case["id"]
            directory = output / name
            directory.mkdir()
            start = time.monotonic()
            config = dict(version=version, case=case, run="s7-swe-" + name,
                          native_root="/native_" + version, fixture_root=str(fixture_root),
                          work=str(directory / "reference-artifacts"))
            write(directory / "reference-request.json", config)
            reference = subprocess.run([sys.executable, "-I", str(HERE / "reference.py"),
                str(directory / "reference-request.json"), str(directory / "reference.json")], capture_output=True, timeout=30)
            (directory / "reference.stdout.txt").write_bytes(reference.stdout)
            (directory / "reference.stderr.txt").write_bytes(reference.stderr)
            assert reference.returncode == 0, (name, reference.stderr.decode())
            raw = json.loads((directory / "reference.json").read_text())
            config["work"] = str(directory / "observed-artifacts")
            captured = capture_native(str(HERE / "adapter.py"), adapter_sha, config, wall_seconds=20)
            write(directory / "capture.json", captured)
            assert captured["health"]["native_complete"] is True, (name, captured)
            assert captured["health"]["transport_intact"] is True, (name, captured)
            assert captured["native"]["returned"] == raw["native"], (name, captured["native"], raw["native"])
            events = [row["event"] for row in captured["transport"]["events"]]
            for site in profile["sites"]:
                facts = raw["facts"][site]
                observations = [e for e in events if e["site"] == site]
                controls.append(dict(id=name + "-" + site, site=site,
                    role="positive" if facts else "negative",
                    reference=dict(source_sha256=reference_sha, recipe_sha256=recipe_sha,
                        output_sha256=digest(facts), native_source_sha256=digest(binding["original_sources"]),
                        framework_semantics_imported=raw["framework_semantics_imported"], facts=facts),
                    observed=observations))
            if case["id"] != "no-native-call":
                calls["native_pipeline_invocations"] += 2
            calls["reference_parser_invocations"] += raw["native_parser_calls"]
            calls["observed_parser_invocations"] += sum(e["site"] == "parser-return" for e in events)
            calls["reference_native_function_calls"] += raw["native_function_calls"]
            row = dict(case=name, native_preserved=True, event_count=len(events),
                       reference_parser_calls=raw["native_parser_calls"], elapsed_seconds=time.monotonic() - start)
            retained.append((case, directory, captured, raw, events, row))
            print(json.dumps(row), flush=True)

        certificate = qualify(profile, binding, controls)
        write(output / (version + "-qualification.json"), certificate)
        assert all(certificate["sites"].values()), certificate["sites"]
        for case, directory, captured, raw, events, row in retained:
            if case["id"] == "no-native-call":
                row["qualification_only"] = True
                all_rows.append(row)
                continue
            # Case population is supplied by the independently retained native
            # reference. It is never reconstructed from potentially lost callbacks.
            identities = {digest(f["identity"]): f["identity"] for facts in raw["facts"].values() for f in facts}
            material = dict(id=row["case"], version="1", inventory=list(identities.values()),
                source_sha256=digest(binding["original_sources"]), input_sha256=digest(case))
            health = dict(binding_sha256=binding["sha256"], sites=certificate["sites"],
                transport={str(captured["producer_pid"]): True},
                native_complete={r["id"]: True for r in profile["rules"]}, qualification_sha256=certificate["sha256"])
            result = evaluate(profile, material, events, health, binding["sha256"])
            write(directory / "case.json", material)
            write(directory / "health.json", health)
            write(directory / "audit.json", result)
            assert set(result["counts"]) == {"CONFORMS"}, (row["case"], result)
            mutations = []
            resolution = next((e for e in events if e["kind"] == "resolution"), None)
            if resolution:
                flipped = copy.deepcopy(events)
                target = next(e for e in flipped if e["id"] == resolution["id"])
                target["values"]["raw"] = "RESOLVED_NO" if target["values"]["raw"] == "RESOLVED_FULL" else "RESOLVED_FULL"
                wrong_resolution = evaluate(profile, material, flipped, health, binding["sha256"])
                substantive = [r for r in wrong_resolution["records"] if r["relationship"] == "resolution-native-aggregate" and r["identity"]["phase"] == "resolution"]
                assert len(substantive) == 1 and substantive[0]["status"] == "VIOLATION"
                mutations.append(dict(control="reversed-native-resolution", passed=True, evidence=wrong_resolution))
            commit = next((e for e in events if e["kind"] == "f2p-commit"), None)
            if commit:
                obligation = commit["identity"]["obligation"]
                changed = copy.deepcopy(events)
                next(e for e in changed if e["id"] == commit["id"])["values"]["test"] = "wrong-committed-native-test"
                contradicted = evaluate(profile, material, changed, health, binding["sha256"])
                assert status(contradicted, "f2p-identity-preserved", obligation, "f2p") == ["VIOLATION"]
                mutations.append(dict(control="wrong-commit-identity", passed=True, evidence=contradicted))
                missing = [e for e in events if e["id"] != commit["id"]]
                absent = evaluate(profile, material, missing, health, binding["sha256"])
                assert status(absent, "f2p-required-commit", obligation, "f2p") == ["VIOLATION"]
                mutations.append(dict(control="lost-required-commit-with-complete-evidence", passed=True, evidence=absent))
                lossy = copy.deepcopy(health)
                lossy["transport"] = {str(captured["producer_pid"]): False}
                uncertain = evaluate(profile, material, missing, lossy, binding["sha256"])
                assert status(uncertain, "f2p-required-commit", obligation, "f2p") == ["INCONCLUSIVE"]
                mutations.append(dict(control="loss-does-not-accuse-native-absence", passed=True, evidence=uncertain))
                witnessed = evaluate(profile, material, changed, lossy, binding["sha256"])
                assert status(witnessed, "f2p-identity-preserved", obligation, "f2p") == ["VIOLATION"]
                mutations.append(dict(control="positive-contradiction-survives-unrelated-loss", passed=True, evidence=witnessed))
            write(directory / "mutation-controls.json", mutations)
            row.update(passed=True, relationships=len(result["records"]),
                       applicable_relationships=sum("no_applicable_disposition" not in r["reasons"] for r in result["records"]),
                       mutation_controls=len(mutations))
            all_rows.append(row)
    summary = dict(passed=True, cases=len(all_rows), rows=all_rows, calls=calls,
        python=sys.version, uid=os.getuid(),
        scope="Already exposed SWE before/after native pytest component pipeline; authored logs, not test execution, independent users or unused historical transfer",
        freeze_sha256=hashlib.sha256((fixture_root / "freeze.json").read_bytes()).hexdigest())
    write(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
