"""Independent batch completeness and role-scoped loss tests."""

import copy

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.batches import extract_batches
from zerorun_harness.binding import generate_binding
from test_native_batches import SOURCE, acquired
from test_complete_batch_policy import run_case, verdict, SOURCE as MEMBERSHIP_SOURCE
from test_producer_health import assess, fixture
from declarative_support import SOURCE as ROLE_SOURCE


@pytest.mark.parametrize("mutation", [
    "duplicate-id", "duplicate-seq", "decreasing-seq", "float-producer",
    "wrong-kind", "wrong-source", "wrong-value-type", "missing-value",
    "extra-field", "wrong-identity-type",
])
def test_semantically_malformed_batch_elements_cannot_establish_completeness(mutation):
    profile, binding, raw, _ = acquired([1, 0])
    first, second = raw[1], raw[2]
    if mutation == "duplicate-id":
        second["id"] = first["id"]
    elif mutation == "duplicate-seq":
        second["seq"] = first["seq"]
    elif mutation == "decreasing-seq":
        first["seq"], second["seq"] = 2, 1
    elif mutation == "float-producer":
        first["producer"] = float(first["producer"])
    elif mutation == "wrong-kind":
        first["kind"] = "absent-kind"
    elif mutation == "wrong-source":
        first["source_sha256"] = "f" * 64
    elif mutation == "wrong-value-type":
        first["values"]["flag"] = "one"
    elif mutation == "missing-value":
        del first["values"]["flag"]
    elif mutation == "extra-field":
        first["unexpected"] = True
    else:
        first["identity"]["candidate"] = False
    with pytest.raises(InvalidEvidence):
        extract_batches(profile, binding, raw)


@pytest.mark.parametrize("mutation", ["negative", "beyond-size", "reverse", "duplicate"])
def test_damaged_ordinal_population_never_claims_complete(mutation):
    profile, binding, raw, _ = acquired([1, 0])
    if mutation == "negative":
        raw[1]["identity"]["obligation"] = -1
    elif mutation == "beyond-size":
        raw[2]["identity"]["obligation"] = 2
    elif mutation == "reverse":
        raw[1]["identity"]["obligation"], raw[2]["identity"]["obligation"] = 1, 0
    else:
        raw[2]["identity"]["obligation"] = 0
    result = extract_batches(profile, binding, raw)
    assert result["batches"][0]["complete"] is False
    assert len(result["events"]) == 2  # Preserve positive evidence; do not invent a repair.


def test_absent_batch_is_distinct_from_witnessed_empty_native_population():
    profile, binding, raw, _ = acquired([])
    empty = extract_batches(profile, binding, raw)
    absent = extract_batches(profile, binding, [])
    assert empty["batches"][0]["complete"] is True
    assert empty["batches"][0]["size"] == 0
    assert absent["batches"] == []
    assert absent["events"] == []


def test_interleaved_distinct_producers_remain_distinct_batches():
    profile, binding, left, _ = acquired([1, 0])
    right = copy.deepcopy(left)
    for event in right:
        event["producer"] = 654
        if "id" in event:
            event["id"] = "654:" + str(event["seq"])
    interleaved = [item for pair in zip(left, right) for item in pair]
    result = extract_batches(profile, binding, interleaved)
    assert len(result["batches"]) == 2
    assert {r["producer"] for r in result["batches"]} == {321, 654}
    assert all(r["complete"] is True for r in result["batches"])


def test_loss_in_one_batch_does_not_rewrite_the_other_producer():
    profile, binding, left, _ = acquired([1, 0])
    right = copy.deepcopy(left)
    for event in right:
        event["producer"] = 654
        if "id" in event:
            event["id"] = "654:" + str(event["seq"])
    result = extract_batches(profile, binding, left[:-1] + right)
    assert {r["producer"]: r["complete"] for r in result["batches"]} == {321: False, 654: True}


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_batch_and_role_additions_never_reinterpret_archived_grammars(version):
    profile, _, _, _ = acquired([1])
    profile["sites"]["return"]["producer_role"] = "parent"
    with pytest.raises(InvalidEvidence):
        generate_binding(profile, {"native.py": SOURCE}, grammar_version=version)


@pytest.mark.parametrize("health", [False, None])
def test_parent_transport_loss_preserves_worker_local_relation_only(health):
    parts = fixture()
    parts[4]["transport"]["11"] = health
    rows = {r["relationship"]: r["status"] for r in assess(parts)["records"]}
    assert rows["commit-required"] == "CONFORMS"
    assert rows["decision-preserved"] == "CONFORMS"
    assert rows["serialization-preserved"] == "INCONCLUSIVE"
    assert rows["parent-local"] == "INCONCLUSIVE"


def test_observed_parent_contradiction_survives_parent_transport_loss():
    parts = fixture()
    parts[4]["transport"]["11"] = False
    next(e for e in parts[3] if e["site"] == "serialize")["values"]["flag"] = 0
    rows = {r["relationship"]: r["status"] for r in assess(parts)["records"]}
    assert rows["serialization-preserved"] == "VIOLATION"
    assert rows["commit-required"] == "CONFORMS"


def test_unrelated_extra_transport_loss_does_not_contaminate_scoped_health():
    parts = fixture()
    parts[4]["transport"]["999"] = False
    assert all(r["status"] == "CONFORMS" for r in assess(parts)["records"])


def test_kind_alias_cannot_hide_relevant_worker_role_loss():
    parts = fixture()
    profile, _, _, events, health = parts
    # One logical fact kind can be declared at sites belonging to both roles.
    # Merely listing the parent alias must not certify absence at the worker site.
    alias = copy.deepcopy(profile["sites"]["accept"])
    alias["producer_role"] = "parent"
    profile["sites"]["parent-accept"] = alias
    profile["sites"]["commit"]["producer_role"] = "parent"
    profile["rules"][0]["requires"] = ["parent-accept", "commit"]
    try:
        binding = generate_binding(profile, {"native.py": ROLE_SOURCE})
        parts = (profile, binding, parts[2], events, health)
        for event in events:
            event["binding_sha256"] = binding["sha256"]
            event["producer"] = 11 if profile["sites"][event["site"]]["producer_role"] == "parent" else 22
            event["id"] = str(event["producer"]) + ":" + str(event["seq"])
        events[:] = [e for e in events if e["producer"] == 11]
        health["binding_sha256"] = binding["sha256"]
        health["transport"]["22"] = False
        health["sites"]["parent-accept"] = True
        result = assess(parts)
    except InvalidEvidence as exc:
        # Only a relevant dependency refusal is an acceptable alternative.
        assert any(word in str(exc).lower() for word in ("role", "coverage", "dependenc"))
        return
    row = next(r for r in result["records"] if r["relationship"] == "commit-required")
    assert row["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("role_mode", [False, True])
def test_empty_batch_control_producer_requires_actual_transport_and_role(role_mode):
    parts = run_case([])
    profile, _, case, events, health, actual = parts
    if role_mode:
        for spec in profile["sites"].values():
            spec["producer_role"] = "parent"
        binding = generate_binding(profile, {"native.py": MEMBERSHIP_SOURCE})
        parts = (profile, binding, case, events, health, actual)
        health["producers"] = {"parent": 321}
        health["binding_sha256"] = binding["sha256"]
        for event in events:
            event["binding_sha256"] = binding["sha256"]
        for payload in health["batch_journal"]:
            payload["binding_sha256"] = binding["sha256"]
    for payload in health["batch_journal"]:
        if payload.get("schema") == "zerorun-native-batch/1":
            payload["producer"] = 999  # No acquired transport/PID ownership for this producer.
    with pytest.raises(InvalidEvidence):
        verdict(parts)


@pytest.mark.parametrize("values", [[], [1]])
@pytest.mark.parametrize("loss", ["all-controls", "empty-journal", "completion", "transport", "qualification"])
def test_empty_or_short_true_population_requires_every_completeness_premise(values, loss):
    parts = run_case(values)
    health = parts[4]
    if loss == "all-controls":
        health["batch_journal"] = []  # Other semantic observations remain available.
    elif loss == "empty-journal":
        health["batch_journal"] = [e for e in health["batch_journal"] if e.get("kind") == "grade"]
    elif loss == "completion":
        health["native_complete"][parts[0]["rules"][0]["id"]] = None
    elif loss == "transport":
        health["transport"]["321"] = None
    else:
        health["sites"]["return"] = None
    assert verdict(parts) == "INCONCLUSIVE"


@pytest.mark.parametrize("values", [[], [1]])
def test_real_end_frame_loss_retains_following_native_grade_as_unknown(values):
    parts = run_case(values)
    # Remove only the lost frame. Do not remove the real, later grade event.
    parts[4]["batch_journal"] = [e for e in parts[4]["batch_journal"] if e.get("stage") != "end"]
    assert verdict(parts) == "INCONCLUSIVE"


def test_witnessed_false_operand_survives_end_loss_and_retained_grade():
    parts = run_case([0])
    for event in parts[3]:
        if event["kind"] == "grade":
            event["values"]["accepted"] = True
    for payload in parts[4]["batch_journal"]:
        if payload.get("kind") == "grade":
            payload["values"]["accepted"] = True
    parts[4]["batch_journal"] = [e for e in parts[4]["batch_journal"] if e.get("stage") != "end"]
    assert verdict(parts) == "VIOLATION"


def test_duplicate_empty_batch_does_not_prove_unique_native_population():
    parts = run_case([])
    controls = copy.deepcopy([p for p in parts[4]["batch_journal"] if "stage" in p])
    for payload in controls:
        payload["batch"] = 2
    parts[4]["batch_journal"] += controls
    assert verdict(parts) == "INCONCLUSIVE"


@pytest.mark.parametrize("field,value", [("size", 1), ("batch", 2), ("producer", 123)])
def test_batch_end_tampering_refuses_inconsistent_population(field, value):
    parts = run_case([])
    next(e for e in parts[4]["batch_journal"] if e.get("stage") == "end")[field] = value
    with pytest.raises(InvalidEvidence):
        verdict(parts)


def test_lost_end_before_distinct_later_batch_preserves_both_receipts():
    profile, binding, first, _ = acquired([1])
    later = copy.deepcopy(first)
    for payload in later:
        if "stage" in payload:
            payload["batch"] = 2
        else:
            payload["seq"] = 2
            payload["id"] = "321:2"
    result = extract_batches(profile, binding, first[:-1] + later)
    assert {r["batch"]: r["complete"] for r in result["batches"]} == {1: False, 2: True}
    assert len(result["events"]) == 2


def guarded_parts():
    parts = fixture()
    profile, _, case, events, health = parts
    rule = next(r for r in profile["rules"] if r["id"] == "decision-preserved")
    rule["guard"] = {"kind": "aggregate", "field": "accepted", "in": [True]}
    rule["requires"].append("aggregate")
    binding = generate_binding(profile, {"native.py": ROLE_SOURCE})
    health["binding_sha256"] = binding["sha256"]
    for event in events:
        event["binding_sha256"] = binding["sha256"]
    return profile, binding, case, events, health


def guarded_row(parts):
    return next(r for r in assess(parts)["records"] if r["relationship"] == "decision-preserved")


def test_true_native_guard_preserves_the_actual_contradiction():
    parts = guarded_parts()
    next(e for e in parts[3] if e["site"] == "commit")["values"]["stored"] = False
    assert guarded_row(parts)["status"] == "VIOLATION"


def test_false_native_guard_requires_witness_and_reports_nonapplicability():
    parts = guarded_parts()
    next(e for e in parts[3] if e["site"] == "commit")["values"]["stored"] = False
    guard = next(e for e in parts[3] if e["site"] == "aggregate")
    guard["values"]["accepted"] = False
    row = guarded_row(parts)
    assert row["status"] == "CONFORMS"
    assert row["reasons"] == ["native_rule_guard_not_applicable"]
    assert guard["id"] in row["evidence_ids"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "other-candidate", "transport", "coverage", "completion"])
def test_guard_ambiguity_or_lost_premise_never_manufactures_applicability(mutation):
    parts = guarded_parts()
    guard = next(e for e in parts[3] if e["site"] == "aggregate")
    if mutation == "missing":
        parts[3].remove(guard)
    elif mutation == "duplicate":
        duplicate = copy.deepcopy(guard)
        duplicate["seq"] = max(e["seq"] for e in parts[3]) + 1
        duplicate["id"] = str(duplicate["producer"]) + ":" + str(duplicate["seq"])
        parts[3].append(duplicate)
    elif mutation == "other-candidate":
        guard["identity"]["candidate"] = "other"
        parts[2]["inventory"].append(copy.deepcopy(guard["identity"]))
    elif mutation == "transport":
        parts[4]["transport"]["11"] = False
    elif mutation == "coverage":
        parts[4]["sites"]["aggregate"] = None
    else:
        parts[4]["native_complete"]["decision-preserved"] = None
    rows = [r for r in assess(parts)["records"] if r["relationship"] == "decision-preserved"]
    assert all(r["status"] == "INCONCLUSIVE" for r in rows)


@pytest.mark.parametrize("guard", [
    {"kind": "aggregate", "field": "accepted", "in": []},
    {"kind": "aggregate", "field": "accepted", "in": [1]},
    {"kind": "aggregate", "field": "missing", "in": [True]},
    {"kind": "missing", "field": "accepted", "in": [True]},
    {"kind": "aggregate", "field": "accepted", "in": [True], "execute": "callback"},
])
def test_guards_remain_finite_typed_declarations(guard):
    parts = guarded_parts()
    rule = next(r for r in parts[0]["rules"] if r["id"] == "decision-preserved")
    rule["guard"] = guard
    with pytest.raises(InvalidEvidence):
        generate_binding(parts[0], {"native.py": ROLE_SOURCE})
