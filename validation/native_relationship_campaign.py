"""Exposed native qualification; source and installed routes use the same controls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

P = Path(os.environ.get("ZERORUN_TEST_PACKAGE", "/package"))
sys.path.insert(0, str(P))
from zerorun_harness.api import digest
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness import (
    capture as capture_bundle,
    audit as audit_bundle,
    compare,
    export,
    report,
)

O = Path(os.environ.get("ZERORUN_TEST_RESULTS", "/results")) / "native-relationships"
O.mkdir(parents=True, exist_ok=False)
F = Path("/fixtures")
adapter = F / "native_adapter.py"
adapter_sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
rows = []
calls = dict(
    authored_evalplus_bank_calls=0,
    swe_native_component_calls=0,
    primary_candidate_bank_calls=0,
)
for family, modes in [
    ("evalplus", ["pass", "fail", "fast-reject"]),
    ("swe", ["pass", "fail", "xfail", "maintenance-fail"]),
]:
    root = F / "native" / family
    profile = json.loads((root / "profile.json").read_text())
    binding = json.loads((root / "binding.json").read_text())
    for mode in modes:
        stem = family + "-" + mode
        baseline = O / (stem + "-reference.json")
        start = time.monotonic()
        reference = subprocess.run(
            [
                sys.executable,
                "-I",
                str(F / "native_reference.py"),
                str(root / "native_api.py"),
                hashlib.sha256((root / "native_api.py").read_bytes()).hexdigest(),
                mode,
                str(baseline),
            ],
            capture_output=True,
            timeout=30,
        )
        (O / (stem + "-reference.stdout.txt")).write_bytes(reference.stdout)
        (O / (stem + "-reference.stderr.txt")).write_bytes(reference.stderr)
        assert reference.returncode == 0, reference.stderr.decode()
        source = "import sys;sys.path.insert(0,sys.argv[1]);import json;from pathlib import Path;from zerorun_harness.telemetry import capture_native;r=capture_native(sys.argv[2],sys.argv[3],json.loads(sys.argv[4]),wall_seconds=15);Path(sys.argv[5]).write_text(json.dumps(r))"
        result_path = O / (stem + "-capture.json")
        observed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                source,
                str(P),
                str(adapter),
                adapter_sha,
                json.dumps({"family": family, "mode": mode}),
                str(result_path),
            ],
            capture_output=True,
            timeout=40,
        )
        (O / (stem + "-observed.stdout.txt")).write_bytes(observed.stdout)
        (O / (stem + "-observed.stderr.txt")).write_bytes(observed.stderr)
        assert observed.returncode == 0, observed.stderr.decode()
        native = json.loads(baseline.read_text())
        capture = json.loads(result_path.read_text())
        assert (
            capture["health"]["native_complete"]
            and capture["health"]["transport_intact"]
        ), capture
        assert capture["native"]["returned"] == native
        events = [e["event"] for e in capture["transport"]["events"]]
        controls = []
        for site, spec in profile["sites"].items():
            facts = [
                {k: f[k] for k in ["identity", "values"]}
                for f in native["facts"]
                if f["kind"] == spec["kind"]
            ]
            assert facts, (family, mode, site)
            controls.append(
                dict(
                    id=stem + "-" + site,
                    site=site,
                    role="positive",
                    reference=dict(
                        source_sha256=hashlib.sha256(
                            (F / "native_reference.py").read_bytes()
                        ).hexdigest(),
                        recipe_sha256=hashlib.sha256(
                            (root / "native_api.py").read_bytes()
                        ).hexdigest(),
                        output_sha256=digest(facts),
                        native_source_sha256=digest(binding["original_sources"]),
                        framework_semantics_imported=False,
                        facts=facts,
                    ),
                    observed=[e for e in events if e["site"] == site],
                )
            )
        certificate = qualify(profile, binding, controls)
        assert all(certificate["sites"].values())
        case = dict(
            id=stem,
            version="1",
            inventory=native["inventory"],
            source_sha256=digest(binding["original_sources"]),
            input_sha256=digest(mode),
        )
        health = dict(
            binding_sha256=binding["sha256"],
            sites=certificate["sites"],
            transport={str(capture["producer_pid"]): True},
            native_complete={"native-aggregate": True},
            qualification_sha256=certificate["sha256"],
        )
        result = evaluate(profile, case, events, health, binding["sha256"])
        expected = "CONFORMS"
        assert result["counts"] == {expected: 1}, result
        # A positive pair with a deliberately changed observed final decision must
        # be distinguished from an unrelated gap; this mutation executes no native code.
        changed = copy.deepcopy(events)
        if events:
            grade = next(e for e in changed if e["kind"] == "grade")
            grade["values"]["raw"] = (
                profile["rules"][0]["target_mapping"]["false"][0]
                if grade["values"]["raw"]
                in profile["rules"][0]["target_mapping"]["true"]
                else profile["rules"][0]["target_mapping"]["true"][0]
            )
            contradicted = evaluate(profile, case, changed, health, binding["sha256"])
            assert contradicted["counts"] == {"VIOLATION": 1}
        for suffix, value in [
            ("qualification", certificate),
            ("audit", result),
            ("case", case),
            ("health", health),
        ]:
            (O / (stem + "-" + suffix + ".json")).write_text(
                json.dumps(value, indent=2)
            )
        calls[
            "authored_evalplus_bank_calls"
            if family == "evalplus"
            else "swe_native_component_calls"
        ] += 2 if family == "evalplus" else 4
        installed_workflow = os.environ.get("ZERORUN_INSTALLED_EXTENSION") == "1"
        if installed_workflow:
            manifest = dict(
                schema="zerorun-extension-manifest/1",
                extension={
                    "id": profile["id"],
                    "version": profile["version"],
                    "sha256": digest(profile),
                },
                binding=binding,
                case=case,
                observations=events,
                health=health,
                qualification=certificate,
            )
            bundle = capture_bundle(manifest)
            assert audit_bundle(bundle) == result
            assert len(compare(bundle, bundle)["records"]) == 1
            assert export(bundle)["native_observations"] == events
            assert "Binding SHA256:" in report(bundle)
            event_replay = export(bundle, mode="event-replay")
            assert (
                evaluate(
                    event_replay["policy"],
                    event_replay["case"],
                    event_replay["events"],
                    event_replay["health"],
                    event_replay["binding_sha256"],
                )
                == result
            )
            assert (
                audit_bundle(export(bundle, mode="integration-replay")["capture"])
                == result
            )
            (O / (stem + "-manifest.json")).write_text(json.dumps(manifest))
            native_root = Path("/tmp") / ("standalone-native-" + family)
            package_name = "evalplus" if family == "evalplus" else "swebench"
            if not native_root.exists():
                native_root.mkdir()
                shutil.copytree(
                    Path("/native_" + family) / package_name,
                    native_root / package_name,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                (native_root / "native_api.py").write_bytes(
                    (root / "native_api.py").read_bytes()
                )
            source_files = {
                p.relative_to(native_root).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in native_root.rglob("*.py")
            }
            recipe = dict(
                schema="zerorun-extension-native-recipe/1",
                source_files=source_files,
                module="native_api",
                function="run",
                args=[mode],
                kwargs={},
                reference_origin_sha256=hashlib.sha256(
                    baseline.read_bytes()
                ).hexdigest(),
                justification="Raw pinned native API aggregate regression qualified against separate native reference",
            )
            script = O / (stem + "-native-regression.py")
            script.write_text(export(bundle, mode="native-regression", recipe=recipe))
            native_output = O / (stem + "-native-regression.json")
            standalone = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(script),
                    "--source",
                    str(native_root),
                    "--output",
                    str(native_output),
                ],
                capture_output=True,
                timeout=30,
            )
            (O / (stem + "-native-regression.stdout.txt")).write_bytes(
                standalone.stdout
            )
            (O / (stem + "-native-regression.stderr.txt")).write_bytes(
                standalone.stderr
            )
            assert standalone.returncode == 0, (
                stem,
                standalone.stderr.decode(),
                native_output.read_text(),
            )
            native_check = json.loads(native_output.read_text())
            assert (
                native_check["native"] == native
                and native_check["result"] == "PASS"
                and native_check["classification_dependency"] is False
            )
            calls[
                "authored_evalplus_bank_calls"
                if family == "evalplus"
                else "swe_native_component_calls"
            ] += 1 if family == "evalplus" else 2
        row = dict(
            case=stem,
            passed=True,
            expected_status=expected,
            native_result_preserved=True,
            reference_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
            capture_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
            elapsed_seconds=time.monotonic() - start,
            installed_extension_workflow=installed_workflow,
        )
        rows.append(row)
        print(json.dumps(row), flush=True)
summary = dict(
    passed=True,
    cases=len(rows),
    rows=rows,
    calls=calls,
    python=sys.version,
    uid=os.getuid(),
    scope="Exposed native API aggregate and binding controls; no internal-worker binding, historical-transfer or independent-user credit",
)
(O / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary), flush=True)
