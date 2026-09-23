"""Exercise actual installed entry points and all five operations outside source."""

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from declarative_support import qualified_manifest
from zerorun_harness import capture, audit, compare, export, report
from zerorun_harness.cli import main
from zerorun_harness.declarative import evaluate
from zerorun_harness.extensions import load_extension

manifest, p = qualified_manifest()
loaded = load_extension(manifest["extension"])
assert loaded == p
bundle = capture(manifest)
result = audit(bundle)
assert result["counts"] == {"CONFORMS": 7}
assert len(compare(bundle, bundle)["records"]) == 7
assert export(bundle)["native_observations"] == manifest["observations"]
event = export(bundle, mode="event-replay")
assert (
    evaluate(
        event["policy"],
        event["case"],
        event["events"],
        event["health"],
        event["binding_sha256"],
    )["sha256"]
    == result["sha256"]
)
integration = export(bundle, mode="integration-replay")
assert audit(integration["capture"])["sha256"] == result["sha256"]
assert "Binding SHA256:" in report(bundle)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    (root / "manifest.json").write_text(json.dumps(manifest))
    assert (
        main(
            [
                "capture",
                str(root / "manifest.json"),
                "--output",
                str(root / "capture.json"),
            ]
        )
        == 0
    )
    for command in ["audit", "compare", "export", "report"]:
        args = [
            command,
            str(root / "capture.json"),
            "--output",
            str(root / (command + ".json")),
        ]
        if command == "compare":
            args.append(str(root / "capture.json"))
        assert main(args) == 0
for family in ["evalplus", "swe"]:
    # Resource selection itself never imports the separate extension package.
    # Load the declared profile bytes from the shipped qualification fixture.
    raw = json.loads(
        (
            Path(__file__).parent
            / "relationship_fixtures/native"
            / family
            / "profile.json"
        ).read_text()
    )
    from zerorun_harness.api import digest

    assert (
        load_extension(
            {"id": raw["id"], "version": raw["version"], "sha256": digest(raw)}
        )
        == raw
    )
print(
    json.dumps(
        {
            "passed": True,
            "installed_profiles": 3,
            "cli_operations": 5,
            "python_api_operations": 5,
            "separate_distribution": "zerorun-exposed-domain 1.0.0",
            "independent_author": False,
            "primary_candidate_calls": 0,
        }
    )
)
