# SPDX-License-Identifier: MIT
"""Native handoff trust boundaries; no native candidate execution in this suite."""

import copy
import hashlib
import json
import subprocess
import sys
from importlib.resources import files

import pytest
from zerorun_harness import audit, capture, export
from zerorun_harness.api import InvalidEvidence, digest, profiles
from zerorun_harness.cli import main


def case(family="evalplus"):
    sha = profiles()[family]["source_sha256"][0]
    if family == "evalplus":
        inp = dict(
            dataset="humaneval",
            entry_point="identity",
            code="def identity(x): return x\n",
            inputs=[[1]],
            expected=[1],
            time_limits=[1.0],
            atol=0.0,
            fast_check=False,
        )
        ref = dict(worker_status=0, progress=1, details=[True])
        primary = "evalplus/eval/__init__.py"
        inputsha = digest(inp["inputs"])
        candidate = hashlib.sha256(inp["code"].encode()).hexdigest()
    else:
        inp = dict(
            log="Unadmitted log\n",
            spec=dict(
                instance_id="example-1",
                repo="pytest-dev/pytest",
                version="7.0",
                FAIL_TO_PASS=["test::one"],
                PASS_TO_PASS=[],
                log_parser="parse_log_pytest",
            ),
        )
        ref = dict(
            selected={},
            found=False,
            report={
                k: dict(success=[], failure=[])
                for k in (
                    "FAIL_TO_PASS",
                    "PASS_TO_PASS",
                    "FAIL_TO_FAIL",
                    "PASS_TO_FAIL",
                )
            },
            resolution="RESOLVED_NO",
        )
        primary = "swebench/harness/grading.py"
        inputsha = hashlib.sha256(inp["log"].encode()).hexdigest()
        candidate = "a" * 64
    b = capture(
        dict(
            records=[
                dict(
                    id="example",
                    family=family,
                    provenance=dict(
                        source_sha256=sha,
                        input_sha256=inputsha,
                        candidate_sha256=candidate,
                    ),
                    observation={},
                    native_reference=None,
                )
            ]
        )
    )
    recipe = dict(
        schema="zerorun-native-recipe/1",
        record_id="example",
        role="policy-protection",
        maintenance_action="Preserve separately observed native state",
        source_files={primary: sha},
        input=inp,
        reference_origin_sha256="b" * 64,
        reference=ref,
        reference_sha256=digest(ref),
    )
    return b, recipe


@pytest.mark.parametrize("family", ["evalplus", "swe"])
def test_native_script_is_classification_independent(family, monkeypatch):
    b, r = case(family)
    before = export(b, mode="native-regression", recipe=r)
    import zerorun_harness.api as api

    monkeypatch.setattr(
        api,
        "audit",
        lambda *a: (_ for _ in ()).throw(RuntimeError("corrupt classifier")),
    )
    assert export(b, mode="native-regression", recipe=r) == before
    assert "import zerorun" not in before and "from zerorun" not in before
    compile(before, "native.py", "exec")
    assert "native-component-regression" in before


def test_event_and_integration_replay(tmp_path):
    manifest = json.loads(
        files("zerorun_harness")
        .joinpath("examples/development-manifest.json")
        .read_text()
    )
    b = capture(manifest)
    assert export(b, mode="event-replay") == b
    copied = export(b, mode="event-replay")
    copied["records"].clear()
    assert b["records"]
    script = tmp_path / "replay.py"
    script.write_text(export(b, mode="integration-replay"), encoding="utf-8")
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert p.returncode == 0 and json.loads(p.stdout) == audit(b)


@pytest.mark.parametrize("mode", [None, True, 1, [], {}, "unknown"])
def test_bad_export_modes(mode):
    b, _ = case()
    with pytest.raises(InvalidEvidence):
        export(b, mode=mode)


@pytest.mark.parametrize(
    "mode", ["native-values", "event-replay", "integration-replay"]
)
def test_recipes_not_silently_ignored(mode):
    b, r = case()
    with pytest.raises(InvalidEvidence):
        export(b, mode=mode, recipe=r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "later"),
        ("record_id", "missing"),
        ("role", "success"),
        ("maintenance_action", ""),
        ("reference_origin_sha256", "x"),
        ("reference_sha256", "0" * 64),
        ("source_files", {}),
        ("input", []),
        ("reference", None),
    ],
)
def test_recipe_envelope_rejects(field, value):
    b, r = case()
    r[field] = value
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


@pytest.mark.parametrize(
    "path",
    [
        "../evalplus/eval/__init__.py",
        "evalplus/../evil.py",
        "/evalplus/a.py",
        "evalplus/a.py:stream",
        "evalplus//a.py",
        "evalplus/./a.py",
        "evalplus/a\\b.py",
        "evalplus/a\x00.py",
    ],
)
def test_source_traversal_rejected(path):
    b, r = case()
    r["source_files"][path] = "a" * 64
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("code", "bad"),
        ("inputs", [[2]]),
        ("time_limits", [True]),
        ("time_limits", [0]),
        ("time_limits", [11]),
        ("time_limits", []),
        ("fast_check", 0),
        ("atol", True),
        ("atol", -1),
        ("expected", []),
        ("dataset", "mbpp"),
    ],
)
def test_worker_arguments_rejected(field, value):
    b, r = case()
    r["input"][field] = value
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


@pytest.mark.parametrize(
    "field,value",
    [
        ("worker_status", False),
        ("progress", True),
        ("details", [1]),
        ("progress", 2),
        ("details", []),
        ("worker_status", 3),
    ],
)
def test_reference_primitive_types(field, value):
    b, r = case()
    r["reference"][field] = value
    r["reference_sha256"] = digest(r["reference"])
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


@pytest.mark.parametrize(
    "field,value",
    [("found", 0), ("selected", {"x": True}), ("resolution", False), ("report", {})],
)
def test_swe_reference_types(field, value):
    b, r = case("swe")
    r["reference"][field] = value
    r["reference_sha256"] = digest(r["reference"])
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


def test_swe_inventory_duplicate_and_input_tamper():
    b, r = case("swe")
    r["input"]["spec"]["FAIL_TO_PASS"] = ["x", "x"]
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)
    b, r = case("swe")
    r["input"]["log"] += "injected"
    with pytest.raises(InvalidEvidence):
        export(b, mode="native-regression", recipe=r)


def test_cli_generated_script_and_exclusive_output(tmp_path):
    b, r = case()
    capturepath = tmp_path / "bundle.json"
    recipepath = tmp_path / "recipe.json"
    out = tmp_path / "native.py"
    capturepath.write_text(json.dumps(b))
    recipepath.write_text(json.dumps(r))
    argv = [
        "export",
        str(capturepath),
        "--mode",
        "native-regression",
        "--recipe",
        str(recipepath),
        "--output",
        str(out),
    ]
    assert main(argv) == 0
    original = out.read_bytes()
    assert main(argv) == 2 and out.read_bytes() == original
    result = tmp_path / "receipt.json"
    p = subprocess.run(
        [
            sys.executable,
            "-I",
            str(out),
            "--source",
            str(tmp_path),
            "--output",
            str(result),
        ],
        capture_output=True,
        text=True,
    )
    assert (
        p.returncode == 2 and json.loads(result.read_text())["result"] == "UNASSESSABLE"
    )
    receipt = result.read_bytes()
    assert (
        subprocess.run(
            [
                sys.executable,
                "-I",
                str(out),
                "--source",
                str(tmp_path),
                "--output",
                str(result),
            ],
            capture_output=True,
        ).returncode
        == 2
    )
    assert result.read_bytes() == receipt


def test_unknown_source_refused():
    b, r = case()
    row = copy.deepcopy(b["records"][0])
    row["provenance"]["source_sha256"] = "0" * 64
    b = capture({"records": [row]})
    with pytest.raises(InvalidEvidence, match="Unsupported native source"):
        export(b, mode="native-regression", recipe=r)
