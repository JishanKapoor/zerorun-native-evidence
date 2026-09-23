"""Independent conventional route parity for the complete finite rule contract.

Expected statuses are authored here before either route runs. Fixture execution
is a local authored Python control, never a native benchmark/candidate campaign.
"""
import copy
import importlib.util
from pathlib import Path

import pytest

from zerorun_harness.declarative import evaluate
from test_complete_batch_policy import run_case
from test_producer_health import fixture
from test_s8_batch_review import guarded_parts


path = Path(__file__).resolve().parents[1] / "ordinary/relationships.py"
spec = importlib.util.spec_from_file_location("separate_ordinary_relationships", path)
ordinary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ordinary)


def compare(parts, relationship, expected):
    profile, binding, case, events, health, *_ = parts
    native_rows = evaluate(profile, case, events, health, binding["sha256"])["records"]
    ordinary_rows = ordinary.run(profile, case, events, health)
    actual = [row["status"] for row in native_rows if row["relationship"] == relationship]
    conventional = [row[2] for row in ordinary_rows if row[0] == relationship]
    assert actual == expected
    assert conventional == expected
    keys = {rule["id"]: rule["keys"] for rule in profile["rules"]}
    assert [(row["relationship"], tuple(row["identity"][key] for key in keys[row["relationship"]]), row["status"])
            for row in native_rows] == ordinary_rows


@pytest.mark.parametrize("guard,corrupt,status", [
    (True, False, "CONFORMS"), (True, True, "VIOLATION"),
    (False, False, "CONFORMS"), (False, True, "CONFORMS"),
])
def test_native_guard_decides_applicability_before_value_contradiction(guard, corrupt, status):
    parts = guarded_parts()
    next(e for e in parts[3] if e["site"] == "aggregate")["values"]["accepted"] = guard
    next(e for e in parts[3] if e["site"] == "commit")["values"]["stored"] = not corrupt
    compare(parts, "decision-preserved", [status])


@pytest.mark.parametrize("loss", ["missing", "duplicate", "guard-coverage", "aliased-coverage", "completion", "transport"])
def test_unknown_guard_or_required_premise_never_becomes_conformance(loss):
    parts = guarded_parts()
    guard = next(e for e in parts[3] if e["site"] == "aggregate")
    if loss == "missing": parts[3].remove(guard)
    elif loss == "duplicate":
        other = copy.deepcopy(guard); other["seq"] += 1; other["id"] += "-duplicate"
        parts[3].append(other)
    elif loss == "guard-coverage": parts[4]["sites"]["aggregate"] = None
    elif loss == "aliased-coverage":
        rule = next(r for r in parts[0]["rules"] if r["id"] == "decision-preserved")
        rule["requires"].remove("reject"); parts[4]["sites"]["reject"] = False
    elif loss == "completion": parts[4]["native_complete"]["decision-preserved"] = False
    else: parts[4]["transport"]["11"] = False
    compare(parts, "decision-preserved", ["INCONCLUSIVE"])


@pytest.mark.parametrize("worker_health", [False, None])
def test_parent_only_rule_ignores_unrelated_worker_transport(worker_health):
    parts = fixture(); parts[4]["transport"]["22"] = worker_health
    compare(parts, "parent-local", ["CONFORMS"])


def test_unresolved_worker_without_worker_events_does_not_hide_parent_proof():
    parts = fixture(); parts[4]["producers"]["worker"] = None
    parts[3][:] = [event for event in parts[3] if event["producer"] == 11]
    parts[4]["transport"]["22"] = False
    compare(parts, "parent-local", ["CONFORMS"])


@pytest.mark.parametrize("values", [[], [1], [1, 1], [1, 0], [0]])
@pytest.mark.parametrize("flip", [False, True])
def test_actual_closed_native_population_controls_inventory_membership(values, flip):
    parts = run_case(values)
    if flip:
        for collection in [parts[3], parts[4]["batch_journal"]]:
            row = next(event for event in collection if event.get("kind") == "grade")
            row["values"]["accepted"] = not row["values"]["accepted"]
    compare(parts, parts[0]["rules"][0]["id"], ["VIOLATION" if flip else "CONFORMS"])


@pytest.mark.parametrize("loss", ["end", "transport", "completion", "coverage"])
def test_short_true_population_without_a_required_premise_is_unknown(loss):
    parts = run_case([1])
    if loss == "end": parts[4]["batch_journal"] = [event for event in parts[4]["batch_journal"] if event.get("stage") != "end"]
    elif loss == "transport": parts[4]["transport"]["321"] = False
    elif loss == "completion": parts[4]["native_complete"][parts[0]["rules"][0]["id"]] = False
    else: parts[4]["sites"]["return"] = False
    compare(parts, parts[0]["rules"][0]["id"], ["INCONCLUSIVE"])


def test_complete_empty_population_has_no_fictitious_source_event():
    parts = run_case([])
    assert not any(event["kind"] == parts[0]["rules"][0]["producer"] for event in parts[3])
    compare(parts, parts[0]["rules"][0]["id"], ["CONFORMS"])


def test_no_batch_receipt_cannot_certify_empty_population():
    parts = run_case([]); parts[4]["batch_journal"] = []
    compare(parts, parts[0]["rules"][0]["id"], ["INCONCLUSIVE"])


def test_false_operand_contradiction_survives_lost_batch_end():
    parts = run_case([0])
    for collection in [parts[3], parts[4]["batch_journal"]]:
        next(event for event in collection if event.get("kind") == "grade")["values"]["accepted"] = True
    parts[4]["batch_journal"] = [event for event in parts[4]["batch_journal"] if event.get("stage") != "end"]
    compare(parts, parts[0]["rules"][0]["id"], ["VIOLATION"])


def test_legacy_no_batch_policy_does_not_inherit_population_closure():
    parts = run_case([1], policy=False)
    compare(parts, parts[0]["rules"][0]["id"], ["INCONCLUSIVE"])


@pytest.mark.parametrize("damage,expected", [("none", "CONFORMS"), ("reordered-scientific", "CONFORMS"),
    ("lost-element", "INCONCLUSIVE"), ("duplicate-position", "CONFORMS"),
    ("duplicate-scientific", "INCONCLUSIVE"), ("lost-end", "CONFORMS")])
def test_separate_acquisition_positions_preserve_scientific_population(damage, expected):
    parts = run_case([1, 1])
    profile, _, case, events, health, _ = parts
    # A finite admitted primitive payload fixture: no class/property is executed.
    # Both old ordinal and new stored scientific IDs address the same two items.
    profile["identity"]["sample"] = "str"
    profile["record_types"] = {"sample": {"module": "native", "name": "Sample", "path": "native.py", "fields": ["ident"]}}
    profile["sites"]["return"]["batch"]["ordinal"] = "acquisition"
    profile["sites"]["return"]["projection"].update(obligation={"literal": 0},
        sample={"item": True, "path": [{"record": "sample", "stored": "ident"}]})
    profile["sites"]["grade"]["projection"].update(obligation={"literal": 0}, sample={"literal": "alpha"})
    profile["rules"][0]["keys"].append("obligation")
    for index, identity in enumerate(case["inventory"]):
        identity.update(obligation=0, sample=["alpha", "beta"][index])
    for collection in (events, health["batch_journal"]):
        for event in collection:
            if "stage" in event:
                event["identity"]["obligation"] = 0
            else:
                original = event["identity"]["obligation"]
                event["identity"].update(obligation=0, sample=["alpha", "beta"][original])
                if event["site"] == "return":
                    event["acquisition"] = {"batch": 1, "ordinal": original}
                    if damage == "reordered-scientific": event["identity"]["sample"] = ["beta", "alpha"][original]
                    if damage == "duplicate-position": event["acquisition"]["ordinal"] = 0
                    if damage == "duplicate-scientific": event["identity"]["sample"] = "alpha"
        if damage == "lost-element":
            collection[:] = [event for event in collection if not (event.get("site") == "return"
                and "id" in event and event["identity"].get("sample") == "beta")]
    if damage == "lost-end": health["batch_journal"] = [e for e in health["batch_journal"] if e.get("stage") != "end"]
    compare(parts, profile["rules"][0]["id"], [expected])


def test_independent_batch_reader_refuses_disagreeing_raw_event():
    parts = run_case([1, 1]); parts[4]["batch_journal"][1]["values"]["flag"] = 0
    with pytest.raises(ValueError, match="journal event differs"):
        ordinary.run(parts[0], parts[2], parts[3], parts[4])


def test_two_complete_batches_do_not_create_one_unique_population():
    parts = run_case([])
    boundaries = copy.deepcopy([event for event in parts[4]["batch_journal"] if "stage" in event])
    for event in boundaries: event["batch"] = 2
    parts[4]["batch_journal"].extend(boundaries)
    compare(parts, parts[0]["rules"][0]["id"], ["INCONCLUSIVE"])


def test_ordinary_module_has_no_production_or_monitoring_import():
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom): imports.append(node.module or "")
    assert set(imports) <= {"json"}
