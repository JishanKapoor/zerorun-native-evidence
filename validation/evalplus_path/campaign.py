"""Frozen one-call native acquisition, independent qualification and re-audit."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from collections import Counter

from expectations import check as check_expectations, applicable, reporting_census

from zerorun_harness.api import digest
from zerorun_harness._telemetry_multiprocess import capture_native_pair
from zerorun_harness.batches import extract_batches
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arithmetic(reference):
    """Independent raw-state assertions; never a primary grade input."""
    worker = reference["journal"]["worker"]
    decisions = [r for r in worker if r["name"].startswith("accept-") or r["name"] == "caught-rejection"]
    increments = [r for r in worker if r["name"] == "progress-write"]
    before = [r for r in worker if r["name"] == "progress-before-write"]
    terminal = [r for r in worker if r["name"].startswith("terminal-progress-")]
    pairs = {}
    for row in before:
        pairs.setdefault(row["identity"]["obligation"], []).append(row["values"]["raw"])
    steps = []
    for row in increments:
        index = row["identity"]["obligation"]
        prior = pairs.get(index, [])
        steps.append(bool(prior) and row["values"]["raw"] == prior.pop(0) + 1)
    return {
        "unit_steps": bool(increments) and all(steps),
        "applicable_dispositions": len(decisions),
        "increment_witnesses": len(increments),
        "terminal_progress": terminal[-1]["values"]["raw"] if terminal else None,
        "completed_count": bool(terminal) and terminal[-1]["values"]["raw"] == len(decisions),
        "scope": "Independent qualification of actual native counter values; no general arithmetic primary contract",
    }


def health(profile, binding, certificate, capture, payloads):
    graph, lifecycle = capture["graph"], capture["lifecycle"]
    pids = {"parent": graph["parent_pid"], "worker": graph["worker_pid"]}
    completed = {}
    for rule in profile["rules"]:
        roles = {profile["sites"][name]["producer_role"] for name in rule["requires"]}
        value = all(lifecycle[role]["complete"] for role in roles)
        if roles == {"parent", "worker"}:
            value = value and graph["intact"] and graph["buffers"]["matched"] is True
        completed[rule["id"]] = bool(value)
    return dict(
        binding_sha256=binding["sha256"], sites=certificate["sites"],
        transport={str(pids[role]): capture["transport"][role]["transport_intact"] is True
                   for role in pids if pids[role] is not None},
        native_complete=completed, qualification_sha256=certificate["sha256"],
        producers=pids, batch_journal=payloads,
    )


def run(prepared, output):
    output.mkdir(parents=True, exist_ok=False)
    design = load(prepared / "design.json")
    for name, expected in design["files"].items():
        if sha(prepared / name) != expected:
            raise ValueError("Frozen preparation changed: " + name)
    adapter = prepared / "implementation/evalplus_path/adapter.py"
    reference_script = prepared / "implementation/evalplus_path/reference.py"
    acquisitions = []
    audits = {}
    relationship_counts = Counter()
    total_relationships = 0
    applicable_relationships = 0
    for variant in design["sources"]:
        root = prepared / variant["id"]
        folder = output / variant["id"]
        folder.mkdir()
        profile, binding = load(root / "profile.json"), load(root / "binding.json")
        controls = []
        acquired = []
        for case in load(root / "controls.json"):
            ident = case["id"]
            result = folder / ident
            result.mkdir()
            case_path = result / "native-case.json"
            save(case_path, case)
            run_id = variant["id"] + ":" + ident
            command = [sys.executable, "-I", str(reference_script), str(root), str(case_path),
                       str(result / "reference"), run_id]
            start = time.monotonic()
            reference_process = subprocess.run(command, capture_output=True, timeout=15)
            (result / "reference.stdout.txt").write_bytes(reference_process.stdout)
            (result / "reference.stderr.txt").write_bytes(reference_process.stderr)
            save(result / "reference-command.json", dict(
                argv=command, returncode=reference_process.returncode,
                wall_seconds=time.monotonic() - start,
                stdout_sha256=hashlib.sha256(reference_process.stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(reference_process.stderr).hexdigest()))
            if reference_process.returncode:
                raise RuntimeError("Independent original reference failed: " + run_id)
            reference = load(result / "reference/reference.json")
            if reference["framework_semantics_imported"]:
                raise RuntimeError("Independent reference imported production semantics")
            capture = capture_native_pair(
                adapter, sha(adapter), {"prepared": str(root), "case": case, "run": run_id},
                wall_seconds=12,
            )
            save(result / "capture.json", capture)
            if "transport" not in capture:
                raise RuntimeError("Native acquisition failed before usable receipt: " + run_id)
            payloads = [packet["event"] for role in ("parent", "worker")
                        for packet in capture["transport"][role]["events"]]
            extracted = extract_batches(profile, binding, payloads)
            save(result / "batch-acquisition.json", extracted)
            observation = extracted["events"]
            reference_rows = reference["journal"]["parent"] + reference["journal"]["worker"]
            for site in profile["sites"]:
                facts = [{"identity": row["identity"], "values": row["values"]}
                         for row in reference_rows if row["name"] == site]
                observed = [event for event in observation if event["site"] == site]
                controls.append(dict(
                    id=ident + ":" + site, site=site, role="positive" if facts else "negative",
                    reference=dict(
                        source_sha256=sha(reference_script), recipe_sha256=reference["recipe_sha256"],
                        output_sha256=digest(facts), native_source_sha256=digest(binding["original_sources"]),
                        framework_semantics_imported=False, facts=facts),
                    observed=observed,
                ))
            preserved = (
                capture["native"] is not None
                and capture["native"]["returned"] == reference["returned"]
                and capture["native"]["exception"] == reference["exception"]
            )
            report = dict(id=run_id, preserved=preserved, capture_status=capture["status"],
                          original_banks=reference["native_bank_calls"],
                          observed_banks=int(capture["graph"]["worker_required"]),
                          arithmetic=arithmetic(reference),
                          same_invocation_buffers=capture["graph"]["buffers"])
            save(result / "preservation.json", report)
            acquired.append((result, case, capture, payloads, observation))
            acquisitions.append(report)
        certificate = qualify(profile, binding, controls)
        save(folder / "qualification.json", certificate)
        for result, case, capture, payloads, observations in acquired:
            material = dict(
                id=variant["id"] + ":" + case["id"], version="1.0.0",
                inventory=[dict(run=variant["id"] + ":" + case["id"], candidate=case["id"],
                                obligation=i, phase="base", attempt=1)
                           for i in range(len(case["inputs"]))],
                source_sha256=digest(binding["original_sources"]), input_sha256=digest(case),
            )
            h = health(profile, binding, certificate, capture, payloads)
            save(result / "case.json", material)
            save(result / "health.json", h)
            audit = evaluate(profile, material, observations, h, binding["sha256"])
            save(result / "audit.json", audit)
            audits[material['id']] = audit
            batches = load(result / 'batch-acquisition.json')['batches']
            reference=load(result/'reference/reference.json')
            selected = applicable(profile,audit,observations,batches,reference)
            save(result / 'applicable-relationships.json', dict(
                total=len(audit['records']),applicable=len(selected),
                excluded_inventory_products=len(audit['records'])-len(selected),
                counts=dict(Counter(row['status'] for row in selected)),records=selected,
                domain_census=reporting_census(profile,audit,reference)))
            total_relationships += len(audit['records'])
            applicable_relationships += len(selected)
            relationship_counts.update(row['status'] for row in selected)
        if not all(certificate["sites"].values()):
            save(folder / "qualification-failures.json", {
                "sites": [name for name, passed in certificate["sites"].items() if not passed],
                "controls": [row for row in certificate["checks"] if not row["passed"]],
            })
    qualifications = [load(output / row["id"] / "qualification.json") for row in design["sources"]]
    expectations = check_expectations(audits,acquisitions)
    save(output / 'declared-expectation-checks.json',expectations)
    summary = dict(
        schema="s8-evalplus-one-call-campaign/1", acquisitions=acquisitions,
        native_bank_calls=sum(row["original_banks"] + row["observed_banks"] for row in acquisitions),
        preserved=all(row["preserved"] for row in acquisitions),
        sites_qualified=all(all(q["sites"].values()) for q in qualifications),
        qualification_controls=sum(len(q["checks"]) for q in qualifications),
        site_declarations=sum(len(q["sites"]) for q in qualifications),
        declared_expectations=all(row['passed'] for row in expectations),
        expectation_checks=len(expectations),
        total_inventory_relationships=total_relationships,
        applicable_relationships=applicable_relationships,
        excluded_inventory_products=total_relationships-applicable_relationships,
        applicable_status_counts=dict(relationship_counts),
        scope="Exposed actual native parent/child path engineering; no primary/human/chronology credit",
    )
    save(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    report = run(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps({k: v for k, v in report.items() if k != "acquisitions"}, indent=2))
    raise SystemExit(0 if report["preserved"] and report["sites_qualified"] and report['declared_expectations'] else 1)
