"""Saved-log reporting bindings and independent reference integrity controls."""
import ast
import hashlib
import importlib
from pathlib import Path
import sys

import pytest

from zerorun_harness.binding import generate_binding, validate_binding
from zerorun_harness.api import digest
from zerorun_harness.declarative import evaluate

VALIDATION = Path(__file__).resolve().parents[1] / "validation"
sys.path.insert(0, str(VALIDATION))
from swe_reporting import declarations as decl
from swe_reporting import reference
from swe_reporting import native_driver


def sources():
    root = VALIDATION / "swe_reporting/source_fixtures"
    return {decl.WRITER: (root / "run_evaluation.py.txt").read_bytes().decode(),
            decl.REPORTING: (root / "reporting.py.txt").read_bytes().decode()}


@pytest.mark.parametrize("path,expected", [
    (decl.WRITER, "0f214f7a578d1c40126fc5c5284c405505fe6d5ba07785d6e2dc06b8e2052ec1"),
    (decl.REPORTING, "d1a3ce73ace1d43bce074575a386ad3143c032a0335bbc29087253c37d007fee"),
])
def test_native_fixture_bytes_preserved(path, expected):
    assert hashlib.sha256(sources()[path].encode()).hexdigest() == expected


@pytest.mark.parametrize("version", ["before", "after"])
def test_reporting_binding_regenerates_and_selects_rewrite_branch(version):
    p = decl.profile(version)
    b = generate_binding(p, sources())
    validate_binding(p, b)
    assert b["grammar_version"] == "1.2.0"
    assert len(b["sites"]) == len(p["sites"]) == 46
    assert {r["site"]: r["line"] for r in b["sites"] if r["site"].startswith("writer-")} == {
        "writer-input": 174, "writer-write": 182, "writer-closed": 183}
    assert all(r["line"] < 190 for r in b["sites"] if r["path"] == decl.WRITER)


def test_reference_source_inventory_matches_declared_sites_independently():
    assert set(reference.site_points()) == set(decl.profile("before")["sites"])
    imports = [n.module for n in ast.walk(ast.parse(Path(reference.__file__).read_text())) if isinstance(n, ast.ImportFrom)]
    assert not any(n and ("zerorun" in n or "declarations" in n) for n in imports)


def test_reference_multiline_assignment_waits_for_native_commit():
    def row(line, event="line", **values):
        return dict(path="p", function="f", call=1, line=line, event=event, locals=values)
    rows = [row(10, report="old"), row(11, report="old"), row(12, report="old"), row(15, report="committed")]
    assert list(reference.point_rows(rows, "p", "f", {10: 12}, "after")) == [rows[-1]]


def test_reference_multiline_exception_is_not_a_committed_assignment():
    rows = [dict(path="p", function="f", call=1, line=10, event="line"),
            dict(path="p", function="f", call=1, line=11, event="exception"),
            dict(path="p", function="f", call=1, line=15, event="line")]
    assert list(reference.point_rows(rows, "p", "f", {10: 12}, "after")) == []


def test_reference_multiline_call_revisited_start_has_one_actual_commit():
    def row(line):
        return dict(path="p", function="f", call=1, line=line, event="line")
    # CPython revisits the assignment start to invoke the function after its
    # multiline arguments. Both entries lead to the same one completed store.
    rows = [row(10), row(11), row(12), row(10), row(15)]
    assert list(reference.point_rows(rows, "p", "f", {10: 12}, "after")) == [rows[-1]]


def test_reference_cache_return_exception_is_not_a_successful_value():
    rows = [dict(path="p", function="f", call=1, line=10, event="line"),
            dict(path="p", function="f", call=1, line=10, event="exception"),
            dict(path="p", function="f", call=1, line=10, event="return", returned=None)]
    assert list(reference.point_rows(rows, "p", "f", {10: 10}, "return")) == []


@pytest.mark.parametrize("category", ["resolved", "unresolved", "incomplete", "empty_patch", "error"])
def test_reference_committed_membership_reads_actual_set(category):
    row = dict(locals={"instance_id": "a", category + "_ids": []})
    f = reference.fact(category + "-commit", row, "run")
    assert f["values"]["raw"] is False
    assert f["identity"]["obligation"] == category


def test_native_import_loader_executes_original_package_initializers(tmp_path):
    # A synthetic import-mechanics fixture, not an SWE benchmark invocation.
    layout = {
        "swebench/__init__.py": "ROOT_INITIALIZER_EXECUTED = True\n",
        "swebench/harness/__init__.py": "HARNESS_INITIALIZER_EXECUTED = True\n",
        "swebench/harness/run_evaluation.py": "from swebench import ROOT_INITIALIZER_EXECUTED\n",
        "swebench/harness/reporting.py": "from swebench.harness import HARNESS_INITIALIZER_EXECUTED\n",
        "swebench/types.py": "NATIVE_TYPES_IMPORTED = True\n",
    }
    for name, content in layout.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    saved = {n: m for n, m in sys.modules.items() if n == "swebench" or n.startswith("swebench.")}
    try:
        evaluation, reporting, types, imported = native_driver.load_native(tmp_path, native_driver.source_inventory(tmp_path))
        assert evaluation.ROOT_INITIALIZER_EXECUTED is True
        assert reporting.HARNESS_INITIALIZER_EXECUTED is True
        assert types.NATIVE_TYPES_IMPORTED is True
        assert imported["swebench"] == "swebench/__init__.py"
        assert imported["swebench.harness"] == "swebench/harness/__init__.py"
    finally:
        for name in list(sys.modules):
            if name == "swebench" or name.startswith("swebench."):
                del sys.modules[name]
        sys.modules.update(saved)
        importlib.invalidate_caches()


def test_native_loader_rejects_added_or_changed_source(tmp_path):
    root = tmp_path / "swebench"
    root.mkdir()
    (root / "__init__.py").write_text("a = 1\n")
    hashes = native_driver.source_inventory(tmp_path)
    (root / "new.py").write_text("pass\n")
    with pytest.raises(ValueError, match="inventory changed"):
        native_driver.load_native(tmp_path, hashes)


def test_frozen_controls_include_real_native_failures_and_artifact_perturbation():
    cases = {r["id"]: r for r in decl.case_definitions()}
    assert len(cases) == 11
    assert cases["write-denied"]["instances"][0]["unwritable"]
    assert cases["missing-log"]["instances"][0]["missing_log"]
    assert cases["changed-file"]["instances"][0]["tamper"] == "flip-resolved"
    assert cases["truncated-file"]["instances"][0]["tamper"] == "truncate-json"
    assert cases["cached-report"]["instances"][0]["cache"]


def test_declared_c3_inventory_retains_missing_operand_as_uncertainty():
    p = decl.profile("before")
    b = generate_binding(p, sources())
    case = decl.case_definitions()[0]
    inventory = decl.case_inventory(case, "unit")
    material = dict(id="unit", version="1", inventory=inventory,
                    source_sha256=digest(b["original_sources"]), input_sha256=digest(case))
    events = []
    for sequence, site in enumerate(["derivation-completed-completed", "derivation-reader", "resolved-membership-resolved"], 1):
        spec = p["sites"][site]
        identity = next(i for i in inventory if i["instance"] == "a" and i["phase"] == "resolution"
                        and i["obligation"] == ("completed" if sequence == 1 else "decision"))
        events.append(dict(id="1:" + str(sequence), producer=1, seq=sequence, site=site,
            kind=spec["kind"], identity=identity, values=dict(raw=True, role=spec["kind"]),
            source_sha256=digest(b["original_sources"]), binding_sha256=b["sha256"]))
    health = dict(binding_sha256=b["sha256"], sites={s: True for s in p["sites"]},
        transport={"1": True}, native_complete={r["id"]: True for r in p["rules"]}, qualification_sha256="a" * 64)
    def conclusion(observations):
        result = evaluate(p, material, observations, health, b["sha256"])
        return next(r for r in result["records"] if r["relationship"] == "native-resolution-derivable"
                    and r["identity"]["instance"] == "a" and r["identity"]["phase"] == "resolution")
    assert conclusion(events)["status"] == "CONFORMS"
    missing = conclusion(events[1:])
    assert missing["status"] == "INCONCLUSIVE"
    assert missing["reasons"] == ["aggregate_native_inventory_gap"]
