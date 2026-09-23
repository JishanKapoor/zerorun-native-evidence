"""Execute prospectively frozen original/native reporting qualification."""
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
from ordinary import check as ordinary_check
if __package__:
    from .domain import reference_domain,select_records,census
else:
    from domain import reference_domain,select_records,census
from zerorun_harness.api import digest
from zerorun_harness.binding import validate_binding
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness.telemetry import capture_native


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def journal(output, row):
    with (output / "attempt-ledger.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def applicable_records(records):
    return [r for r in records if r['evidence_ids'] and r['reasons'] not in
            (['no_applicable_disposition'], ['native_rule_guard_not_applicable'])]


def relationship_status(result, name):
    return [r["status"] for r in applicable_records(result["records"]) if r["relationship"] == name]


def controls_for_events(profile, material, events, health, binding):
    """Retained-event observer faults; no new native invocation."""
    rows = []
    for site, relationship in [('list-f2p-success-stored', 'native-commit-lists-report-preserved'),
                               ('tests-embedded', 'grading-embedded-preserved'),
                               ('writer-input', 'native-report-writer-preserved'),
                               ('resolution-embedded', 'native-resolution-report-preserved')]:
        target = next((e for e in events if e['site'] == site), None)
        if target is None:
            continue
        changed = copy.deepcopy(events)
        changed_value = next(e for e in changed if e['id'] == target['id'])['values']
        changed_value['raw'] = not changed_value['raw'] if type(changed_value['raw']) is bool else changed_value['raw'] + ' corrupted'
        bad = evaluate(profile, material, changed, health, binding)
        assert 'VIOLATION' in relationship_status(bad, relationship)
        rows.append(dict(id='wrong-native-bridge-' + site, passed=True, audit=bad))
    target = next((e for e in events if e["kind"] == "category-commit" and e["identity"]["obligation"] == "resolved"), None)
    if target is None:
        return rows
    changed = copy.deepcopy(events)
    next(e for e in changed if e["id"] == target["id"])["values"]["raw"] = False
    bad = evaluate(profile, material, changed, health, binding)
    assert "VIOLATION" in relationship_status(bad, "category-membership-preservation")
    rows.append(dict(id="wrong-actual-membership", passed=True, audit=bad))
    missing = [e for e in events if e["id"] != target["id"]]
    bad = evaluate(profile, material, missing, health, binding)
    assert "VIOLATION" in relationship_status(bad, "category-required-commit")
    rows.append(dict(id="missing-required-commit", passed=True, audit=bad))
    lossy = copy.deepcopy(health)
    lossy["transport"] = {p: False for p in health["transport"]}
    uncertain = evaluate(profile, material, missing, lossy, binding)
    assert "VIOLATION" not in relationship_status(uncertain, "category-required-commit")
    assert "INCONCLUSIVE" in relationship_status(uncertain, "category-required-commit")
    rows.append(dict(id="missing-commit-with-transport-loss", passed=True, audit=uncertain))
    contradiction = evaluate(profile, material, changed, lossy, binding)
    assert "VIOLATION" in relationship_status(contradiction, "category-membership-preservation")
    rows.append(dict(id="positive-contradiction-survives-loss", passed=True, audit=contradiction))
    population = next(e for e in events if e["kind"] == "aggregate" and e["identity"]["obligation"] == "resolved")
    changed = copy.deepcopy(events)
    next(e for e in changed if e["id"] == population["id"])["values"]["count"] += 1
    bad = evaluate(profile, material, changed, health, binding)
    assert "VIOLATION" in relationship_status(bad, "aggregate-cardinality-preserved")
    rows.append(dict(id="wrong-serialized-cardinality", passed=True, audit=bad))
    member = next(e for e in events if e["kind"] == "resolved-member" and e["values"]["raw"] is True)
    changed = copy.deepcopy(events)
    next(e for e in changed if e["id"] == member["id"])["values"]["raw"] = False
    bad = evaluate(profile, material, changed, health, binding)
    assert "VIOLATION" in relationship_status(bad, "native-resolution-derivable")
    rows.append(dict(id="wrong-native-conjunction-membership", passed=True, audit=bad))
    return rows


def run(fixtures, output):
    fixtures, output = Path(fixtures), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    freeze = json.loads((fixtures / "freeze.json").read_text())
    cases = json.loads((fixtures / "cases.json").read_text())
    assert digest(cases) == freeze["case_sha256"]
    for name, expected in freeze["helper_sha256"].items():
        assert sha(HERE / name) == expected, name
    import zerorun_harness
    package = Path(zerorun_harness.__file__).parent
    for name, expected in freeze["core_sha256"].items():
        assert sha(package / name) == expected, name
    all_rows = []
    reference_sha = digest({n: sha(HERE / n) for n in ["reference.py", "internal_reference.py"]})
    recipe_sha, adapter_sha = sha(HERE / "native_driver.py"), sha(HERE / "adapter.py")
    for version in ["before", "after"]:
        profile = json.loads((fixtures / version / "profile.json").read_text())
        binding = json.loads((fixtures / version / "binding.json").read_text())
        inventories = json.loads((fixtures / version / "inventories.json").read_text())
        assert digest(profile) == freeze["versions"][version]["profile_sha256"]
        assert binding["sha256"] == freeze["versions"][version]["binding_sha256"]
        assert digest(inventories) == freeze["versions"][version]["inventory_sha256"]
        validate_binding(profile, binding)
        controls, retained = [], []
        for case in cases:
            name = version + "-" + case["id"]
            directory = output / name
            directory.mkdir()
            options = dict(version=version, fixture_root=str(fixtures), native_root="/native_" + version,
                run="s8-" + name, case=case, work="/tmp/" + name + "-reference",
                call_journal=str(directory / "reference-calls.jsonl"), retained_work=str(directory / "reference-artifacts"),
                raw_reference=str(directory / "reference-raw.json"))
            write(directory / "reference-request.json", options)
            journal(output, dict(case=name, phase="reference-entered", request_sha256=sha(directory / "reference-request.json")))
            start = time.monotonic()
            proc = subprocess.run([sys.executable, "-I", str(HERE / "reference.py"),
                str(directory / "reference-request.json"), str(directory / "reference.json")], capture_output=True, timeout=60)
            (directory / "reference.stdout.txt").write_bytes(proc.stdout)
            (directory / "reference.stderr.txt").write_bytes(proc.stderr)
            journal(output, dict(case=name, phase="reference-exit", returncode=proc.returncode, elapsed_seconds=time.monotonic() - start))
            assert proc.returncode == 0, (name, proc.stderr.decode(errors="replace"))
            reference = json.loads((directory / "reference.json").read_text())
            options.update(work="/tmp/" + name + "-observed", native_output=str(directory / "observed-native.json"),
                call_journal=str(directory / "observed-calls.jsonl"), retained_work=str(directory / "observed-artifacts"))
            write(directory / "capture-request.json", options)
            journal(output, dict(case=name, phase="observed-entered", request_sha256=sha(directory / "capture-request.json")))
            start = time.monotonic()
            capture = capture_native(str(HERE / "adapter.py"), adapter_sha, options, wall_seconds=45)
            write(directory / "capture.json", capture)
            journal(output, dict(case=name, phase="observed-exit", elapsed_seconds=time.monotonic() - start,
                native_complete=capture["health"]["native_complete"], transport_intact=capture["health"]["transport_intact"]))
            assert capture["health"]["native_complete"] and capture["health"]["transport_intact"], (name, capture)
            assert sha(directory / "observed-native.json") == capture["native"]["returned"]["output_sha256"]
            observed = json.loads((directory / "observed-native.json").read_text())
            assert observed == reference["native"], (name, "original and observed native/artifact outputs differ")
            assert observed["quiescent_handoff"]
            events = [r["event"] for r in capture["transport"]["events"]]
            for site in profile["sites"]:
                facts = reference["facts"][site]
                controls.append(dict(id=name + "-" + site, site=site, role="positive" if facts else "negative",
                    reference=dict(source_sha256=reference_sha, recipe_sha256=recipe_sha,
                        output_sha256=digest(facts), native_source_sha256=digest(binding["original_sources"]),
                        framework_semantics_imported=False, facts=facts), observed=[e for e in events if e["site"] == site]))
            ordinary = ordinary_check(reference)
            write(directory / "ordinary.json", ordinary)
            retained.append((case, directory, reference, observed, events, capture, ordinary))
            print(json.dumps(dict(case=name, native_preserved=True, events=len(events),
                native_operations=len(observed["operations"]), reference_function_calls=reference["native_function_calls"])), flush=True)
        certificate = qualify(profile, binding, controls)
        write(output / (version + "-qualification.json"), certificate)
        assert all(certificate["sites"].values()), certificate["sites"]
        touched = {(r["path"], r["function"], r["line"]) for _, _, ref, *_ in retained for r in ref["traces"] if r["event"] == "line"}
        coverage = [{**r, "native_line_executed": (r["path"], r["function"], r["line"]) in touched} for r in binding["sites"]]
        write(output / (version + "-static-coverage.json"), coverage)
        assert all(r["native_line_executed"] for r in coverage)
        for case, directory, reference, observed, events, capture, ordinary in retained:
            row = dict(case=directory.name, native_preserved=True, native_operations=len(observed["operations"]),
                reference_function_calls=reference["native_function_calls"],
                reference_calls_by_function=reference["native_calls_by_function"],
                native_exceptions=[r["exception"] for r in observed["operations"] if r["exception"]])
            if case["id"] == "no-native-call":
                row["qualification_only"] = True
                all_rows.append(row)
                continue
            material = dict(id=directory.name, version="1", inventory=inventories[case["id"]],
                source_sha256=digest(binding["original_sources"]), input_sha256=digest(case))
            aggregate_ok = all(r["exception"] is None for r in observed["operations"] if r["operation"] == "aggregate")
            writer_ok = all(r["exception"] is None for r in observed["operations"] if r["operation"] == "rewrite")
            completion = {r["id"]: writer_ok if r["id"].startswith("writer-") else aggregate_ok for r in profile["rules"]}
            health = dict(binding_sha256=binding["sha256"], sites=certificate["sites"],
                transport={str(capture["producer_pid"]): True}, native_complete=completion,
                qualification_sha256=certificate["sha256"])
            result = evaluate(profile, material, events, health, binding["sha256"])
            write(directory / "case.json", material)
            write(directory / "health.json", health)
            write(directory / "audit.json", result)
            original_aggregate_ok=all(r['exception'] is None for r in reference['native']['operations'] if r['operation']=='aggregate')
            original_writer_ok=all(r['exception'] is None for r in reference['native']['operations'] if r['operation']=='rewrite')
            original_completion={r['id']:original_writer_ok if r['id'].startswith('writer-') else original_aggregate_ok for r in profile['rules']}
            domain=reference_domain(profile,reference['facts'],original_completion,material['inventory'])
            write(directory/'native-domain.json',census(result['records'],domain))
            relevant = select_records(result["records"],domain)
            violations = [r for r in relevant if r["status"] == "VIOLATION"]
            if case["id"] == "changed-file":
                assert len(violations) == 1 and violations[0]["relationship"] == "consumed-report-preserves-closed-writer"
                assert any(not r["preserved"] for r in ordinary["handoffs"].values())
            else:
                assert not violations, (directory.name, violations)
                assert all(r["preserved"] for r in ordinary["handoffs"].values())
            if aggregate_ok and writer_ok:
                assert all(r["status"] == "CONFORMS" or r in violations for r in relevant), (directory.name, relevant)
            else:
                assert any(r["status"] == "INCONCLUSIVE" for r in relevant)
            assert all(all(c.values()) for c in ordinary["aggregate_checks"])
            assert all(ordinary["actual_final_file_preserved"])
            assert all(c['passed'] for c in ordinary['internal_checks'])
            mutations = controls_for_events(profile, material, events, health, binding["sha256"]) if aggregate_ok and writer_ok else []
            write(directory / "mutation-controls.json", mutations)
            row.update(passed=True, relationships=len(result["records"]), applicable_relationships=len(relevant),
                excluded_empty_evidence_products=len(result["records"]) - len(relevant),
                vacuous_no_disposition_products=sum(r["reasons"] == ["no_applicable_disposition"] for r in result["records"]),
                declared_inventory_entries=len(material["inventory"]),
                applicable_counts={s: sum(r["status"] == s for r in relevant) for s in sorted({r["status"] for r in relevant})},
                reference_witnessed_relationships=sum('basis' not in r for r in domain['rows']),
                unresolved_interrupted_domains=sum('basis' in r for r in domain['rows']),
                mutation_controls=len(mutations), ordinary_matches=True)
            all_rows.append(row)
    summary = dict(passed=True, rows=all_rows, cases=len(all_rows), primary_candidate_calls=0,
        python=sys.version, uid=os.getuid(), image_scope="Separate S8 pinned dependency image",
        freeze_sha256=sha(fixtures / "freeze.json"),
        scope="Same-invocation original parser/grading/native writer/reader/aggregate, one-instance exposed development only; no Docker patch execution")
    write(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
