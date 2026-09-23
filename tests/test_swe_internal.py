"""Finite source binding and independent-reference integrity controls."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

from zerorun_harness.api import InvalidEvidence, digest
from zerorun_harness.binding import generate_binding, validate_binding
from zerorun_harness.qualification import qualify

HELPERS = Path(__file__).resolve().parents[1] / "validation/swe_internal"
sys.path.insert(0, str(HELPERS))
from declarations import GRADING, PARSER, REVISIONS, profile
from reference import fact, point_rows, reference_sites


def sources(version):
    root = HELPERS / "source_fixtures" / version
    return {GRADING: (root / "grading.py.txt").read_bytes().decode(), PARSER: (root / "parser.py.txt").read_bytes().decode()}


@pytest.mark.parametrize("version,grading_sha", [
    ("before", "c891dee92350f8927abfdf8a7c5c664df7838f1c65f2ffe069f854c5ec57ff95"),
    ("after", "f58def5253794854b9f20de1ac5533555af379fdf731763077c75fa1258b4961"),
])
def test_bundled_native_sources_are_exact_upstream_bytes(version, grading_sha):
    source = sources(version)
    assert hashlib.sha256(source[GRADING].encode()).hexdigest() == grading_sha
    assert hashlib.sha256(source[PARSER].encode()).hexdigest() == "cd56156414f8327221e525665ace9b184f7d73e83b272d9eb3f545fb17c2d9bc"


@pytest.mark.parametrize("version", list(REVISIONS))
def test_exact_original_native_sources_bind_and_regenerate(version):
    p = profile(version)
    b = generate_binding(p, sources(version))
    assert b["grammar_version"] == "1.1.0"
    validate_binding(p, b)
    assert set(reference_sites(version)) == set(p["sites"])
    assert set(b["original_sources"]) == {GRADING, PARSER}
    assert all("__zr_observe" in text for text in b["transformed"].values())


@pytest.mark.parametrize("version", list(REVISIONS))
@pytest.mark.parametrize("name", ["selected-return", "f2p-decision-success", "p2p-commit-failure", "report-return"])
def test_missing_actual_native_anchor_refuses_qualification(version, name):
    p = profile(version)
    p["sites"][name]["anchor"] = "invented_native_variable = 123"
    with pytest.raises(InvalidEvidence):
        generate_binding(p, sources(version))


@pytest.mark.parametrize("bank", ["f2p", "p2p"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_reference_commit_reads_actual_list_tail(bank, outcome):
    name = "native-test"
    state = {"test_case": name, "eval_status_map": {name: "SKIPPED"}, "success": ["actual-last-commit"], "failed": ["actual-last-commit"]}
    decision = fact(bank + "-decision-" + outcome, {"locals": state})
    committed = fact(bank + "-commit-" + outcome, {"locals": state})
    assert decision["values"]["test"] == name
    assert committed["values"]["test"] == "actual-last-commit"
    assert committed["values"]["accepted"] is (outcome == "success")
    assert committed["identity"]["phase"] == bank


def test_reference_missing_status_is_not_silent_success():
    record = fact("f2p-decision-failure", {"locals": {"test_case": "absent", "eval_status_map": {}}})
    assert record["values"]["raw"] == "MISSING"
    assert record["values"]["accepted"] is False


def test_reference_parser_store_reads_actual_cell_not_preceding_decision():
    row = {"locals": {"test_case": ["PASSED", "native-test"], "test_status_map": {"native-test": "FAILED"}}}
    assert fact("parser-decision", row)["values"]["raw"] == "PASSED"
    assert fact("parser-write", row)["values"]["raw"] == "FAILED"


def test_reference_after_state_follows_same_native_call_not_nested_call():
    rows = [dict(call=1, path=GRADING, function="f", line=12, event="line", locals={"x": 0}),
            dict(call=2, path=GRADING, function="f", line=12, event="line", locals={"x": 4}),
            dict(call=2, path=GRADING, function="f", line=13, event="return", locals={"x": 5}),
            dict(call=1, path=GRADING, function="f", line=13, event="line", locals={"x": 1})]
    outputs = list(point_rows(rows, GRADING, "f", {12}, "after"))
    assert [r["locals"]["x"] for r in outputs] == [1, 5]


def test_reference_return_reconciles_context_exit_line_to_actual_native_return():
    rows = [dict(call=1, path=GRADING, function="f", line=20, event="line", locals={"x": 1}),
            dict(call=1, path=GRADING, function="f", line=10, event="line", locals={"x": 1}),
            dict(call=1, path=GRADING, function="f", line=10, event="return", locals={"x": 1}, returned=[{}, True])]
    result = list(point_rows(rows, GRADING, "f", {20}, "return"))
    assert len(result) == 1
    assert result[0]["returned"] == [{}, True]


def test_mutation_result_selection_preserves_native_phase():
    import ast
    module = ast.parse((HELPERS / "campaign.py").read_text())
    function, = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "status"]
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "campaign.py", "exec"), namespace)
    rows = [dict(relationship="f2p-required-commit", identity={"obligation": "same-test", "phase": phase}, status=status)
            for phase, status in [("parser", "CONFORMS"), ("f2p", "VIOLATION")]]
    assert namespace["status"]({"records": rows}, "f2p-required-commit", "same-test", "f2p") == ["VIOLATION"]


@pytest.mark.parametrize("version", list(REVISIONS))
def test_f2p_skipped_differs_from_p2p_skipped_in_visible_policy(version):
    p = profile(version)
    rules = {r["id"]: r for r in p["rules"]}
    assert "SKIPPED" not in rules["f2p-native-status-policy"]["statuses"]
    assert "SKIPPED" in rules["p2p-native-status-policy"]["statuses"]
    assert all(r["operator"] in {"exists", "identity", "all_in"} for r in p["rules"])


def test_reference_module_has_no_production_import_or_profile_normalization():
    import ast
    tree = ast.parse((HELPERS / "reference.py").read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name.startswith(("zerorun_harness", "declarations")) for name in imports)


def test_reference_detects_wrong_observer_identity_in_full_qualification():
    p = profile("after")
    b = generate_binding(p, sources("after"))
    expected = fact("f2p-decision-success", {"locals": {"test_case": "a", "eval_status_map": {"a": "PASSED"}}})
    observed = {"site": "f2p-decision-success", "binding_sha256": b["sha256"], **copy.deepcopy(expected)}
    observed["identity"]["obligation"] = "wrong-native-test"
    def control(role, facts, events):
        return dict(id="identity-" + role, site="f2p-decision-success", role=role,
            reference=dict(source_sha256="a" * 64, recipe_sha256="b" * 64, output_sha256=digest(facts),
                native_source_sha256=digest(b["original_sources"]), framework_semantics_imported=False, facts=facts), observed=events)
    q = qualify(p, b, [control("positive", [expected], [observed]), control("negative", [], [])])
    assert q["sites"]["f2p-decision-success"] is False
