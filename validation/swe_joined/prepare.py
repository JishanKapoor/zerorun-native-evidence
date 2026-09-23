"""Freeze exposed controls, source bytes and helpers before native execution."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))
from declarations import REVISIONS, SOURCES, profile, case_definitions, case_inventory
from native_driver import source_inventory
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding


def prepare(workspace, output):
    workspace, output = Path(workspace), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases = case_definitions()
    (output / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    freeze = dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope="One-instance joined native parser/grading/rewrite/reader/aggregate development; no Docker patch execution",
        quiescent_closed_file_handoff=True, primary_candidate_calls=0,
        case_sha256=digest(cases), versions={})
    image_evidence = workspace / "study_s8/swe/image-r1"
    image_record = json.loads((image_evidence / "dependency-image-identity.stdout.txt").read_text())[0]
    freeze["dependency_image"] = dict(image_id=image_record["Id"],
        install_report_sha256=hashlib.sha256((image_evidence / "dependency-install.json").read_bytes()).hexdigest(),
        environment_freeze_sha256=hashlib.sha256((image_evidence / "dependency-freeze.txt").read_bytes()).hexdigest())
    for version, revision in REVISIONS.items():
        root = workspace / "evidence/phase1/legacy-development/feasibility_swe" / version / ("SWE-bench-" + revision)
        policy = profile(version)
        binding = generate_binding(policy, {p: (root / p).read_text(encoding="utf-8") for p in SOURCES})
        hashes = source_inventory(root)
        inventories = {case["id"]: case_inventory(case, "s8-" + version + "-" + case["id"]) for case in cases}
        directory = output / version
        directory.mkdir()
        for name, value in [("profile", policy), ("binding", binding), ("source-hashes", hashes), ("inventories", inventories)]:
            (directory / (name + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")
        freeze["versions"][version] = dict(revision=revision, profile_sha256=digest(policy),
            binding_sha256=binding["sha256"], source_inventory_sha256=digest(hashes), inventory_sha256=digest(inventories),
            logical_views=len(policy["sites"]), static_source_matches=len(binding["sites"]),
            distinct_native_statements=len({(r["path"], r["function"], r["line"]) for r in binding["sites"]}),
            distinct_statement_positions=len({(r["path"], r["function"], r["line"], r["position"]) for r in binding["sites"]}))
    freeze["helper_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))}
    freeze["core_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((HERE.parents[1] / "src/zerorun_harness").glob("*.py"))}
    (output / "freeze.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    return freeze


if __name__ == "__main__":
    print(json.dumps(prepare(sys.argv[1], sys.argv[2]), indent=2))
