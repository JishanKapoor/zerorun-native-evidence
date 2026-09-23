"""Seal exposed source/case declarations before the native campaign runs."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))
from declarations import GRADING, PARSER, REVISIONS, case_definitions, profile
from native_driver import source_inventory
from zerorun_harness.binding import generate_binding
from zerorun_harness.api import digest


def prepare(workspace, output):
    workspace, output = Path(workspace), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"scope": "Prospective exposed development; no unused historical or primary cohort credit", "versions": {}, "case_sha256": digest(case_definitions())}
    (output / "cases.json").write_text(json.dumps(case_definitions(), indent=2))
    for version, revision in REVISIONS.items():
        root = workspace / "evidence/phase1/legacy-development/feasibility_swe" / version / ("SWE-bench-" + revision)
        sources = {relative: (root / relative).read_bytes().decode("utf-8") for relative in [GRADING, PARSER]}
        policy = profile(version)
        binding = generate_binding(policy, sources)
        hashes = source_inventory(root)
        directory = output / version
        directory.mkdir()
        for name, value in [("profile", policy), ("binding", binding), ("source-hashes", hashes)]:
            (directory / (name + ".json")).write_text(json.dumps(value, indent=2))
        manifest["versions"][version] = {"revision": revision, "profile_sha256": digest(policy), "binding_sha256": binding["sha256"], "source_inventory_sha256": digest(hashes)}
    manifest["implementation_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))}
    (output / "freeze.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    print(json.dumps(prepare(sys.argv[1], sys.argv[2]), indent=2))
