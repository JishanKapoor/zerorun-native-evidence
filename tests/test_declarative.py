# SPDX-License-Identifier: MIT
import copy
import itertools
import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import UnsupportedBinding, generate_binding
from zerorun_harness.declarative import evaluate, validate_profile
from declarative_support import SOURCE, execute, profile


def assess(items):
    p, binding, case, events, health, _ = items
    return evaluate(p, case, events, health, binding["sha256"])


@pytest.mark.parametrize("values", list(itertools.product([True, False], repeat=3)))
def test_native_dispositions_are_preserved(values):
    items = execute(values)
    result = assess(items)
    assert result["counts"] == {"CONFORMS": 10}
    assert items[-1] == (dict(enumerate(values)), 3, all(values))
    assert [
        e["values"]["accepted"] for e in items[3] if e["kind"] == "decision"
    ] == list(values)


@pytest.mark.parametrize("value", [True, False])
def test_omitted_commit_after_both_dispositions(value):
    items = execute([value], omit=True)
    rows = assess(items)["records"]
    assert (
        next(r for r in rows if r["relationship"] == "commit-required")["status"]
        == "VIOLATION"
    )
    assert items[-1] == ({}, 0, True)


def test_precomparison_continue_invents_no_acceptance():
    items = execute([None, True])
    assert [
        e["identity"]["obligation"] for e in items[3] if e["kind"] == "decision"
    ] == [1]
    rows = assess(items)["records"]
    assert not any(r["status"] == "VIOLATION" for r in rows)
    assert (
        next(r for r in rows if r["relationship"] == "aggregate-derived")["status"]
        == "INCONCLUSIVE"
    )


@pytest.mark.parametrize(
    "native_grade,status", [(False, "CONFORMS"), (True, "VIOLATION")]
)
def test_witnessed_failure_prefix_determines_native_conjunction(native_grade, status):
    items = execute([False, None])
    next(e for e in items[3] if e["kind"] == "aggregate")["values"]["accepted"] = (
        native_grade
    )
    rows = assess(items)["records"]
    assert (
        next(r for r in rows if r["relationship"] == "aggregate-derived")["status"]
        == status
    )


def test_contradictory_pair_survives_unrelated_missing_site():
    items = execute([True], corrupt=True)
    items[4]["sites"]["serialize"] = False
    items[4]["native_complete"]["decision-preserved"] = False
    items[4]["transport"]["999"] = False
    rows = assess(items)["records"]
    assert (
        next(r for r in rows if r["relationship"] == "decision-preserved")["status"]
        == "VIOLATION"
    )
    assert (
        next(r for r in rows if r["relationship"] == "serialization-preserved")[
            "status"
        ]
        == "INCONCLUSIVE"
    )


@pytest.mark.parametrize("premise", ["coverage", "transport", "native"])
def test_no_absence_accusation_with_missing_premise(premise):
    items = execute([True], omit=True)
    if premise == "coverage":
        items[4]["sites"]["commit"] = False
    if premise == "transport":
        items[4]["transport"]["999"] = False
    if premise == "native":
        items[4]["native_complete"]["commit-required"] = False
    assert (
        next(
            r
            for r in assess(items)["records"]
            if r["relationship"] == "commit-required"
        )["status"]
        == "INCONCLUSIVE"
    )


def test_actual_type_not_python_bool_int_equality():
    items = execute([True])
    event = next(e for e in items[3] if e["kind"] == "serialized")
    event["values"]["flag"] = True
    with pytest.raises(InvalidEvidence, match="type mismatch"):
        assess(items)


def test_wrong_identity_is_not_relabelled_native_failure():
    items = execute([True])
    items[3][0]["identity"]["candidate"] = "unobserved-candidate"
    with pytest.raises(InvalidEvidence, match="outside declared"):
        assess(items)


def test_duplicate_identity_is_ambiguous():
    items = execute([True])
    copy_event = copy.deepcopy(items[3][0])
    copy_event.update(id="other-producer:1", producer=777, seq=1)
    items[3].append(copy_event)
    items[4]["transport"]["777"] = True
    rows = assess(items)["records"]
    assert (
        next(r for r in rows if r["relationship"] == "commit-required")["status"]
        == "INCONCLUSIVE"
    )


def test_incorrect_aggregate_is_witnessed_contradiction():
    items = execute([True, False])
    next(e for e in items[3] if e["kind"] == "aggregate")["values"]["accepted"] = True
    rows = assess(items)["records"]
    assert (
        next(r for r in rows if r["relationship"] == "aggregate-derived")["status"]
        == "VIOLATION"
    )


def test_missing_callback_with_intact_transport_is_coverage_failure():
    items = execute([True])
    items[3][:] = [e for e in items[3] if e["site"] != "commit"]
    items[4]["sites"]["commit"] = False
    assert not any(r["status"] == "VIOLATION" for r in assess(items)["records"])


def test_changed_binding_cannot_retarget_old_evidence():
    items = execute([True])
    items[3][0]["binding_sha256"] = "0" * 64
    with pytest.raises(InvalidEvidence, match="Mixed source"):
        assess(items)


@pytest.mark.parametrize(
    "replacement",
    ["details[obligation] = not stored", "details[obligation + 1] = stored"],
)
def test_unknown_native_realization_refused(replacement):
    with pytest.raises(UnsupportedBinding, match="multiplicity"):
        generate_binding(
            profile(),
            {"native.py": SOURCE.replace("details[obligation] = stored", replacement)},
        )


def test_native_expression_is_evaluated_once():
    p = profile()
    source = SOURCE.replace(
        "stored = not decision if corrupt else decision", "stored = tick(decision)"
    )
    b = generate_binding(p, {"native.py": source})
    calls, events = [], []
    scope = {
        "tick": lambda v: calls.append(v) or v,
        "__zr_observe": lambda site, state: events.append(site),
    }
    exec(b["transformed"]["native.py"], scope)
    assert scope["evaluate"]("r", "c", "base", 1, [True, False]) == (
        {0: True, 1: False},
        2,
        False,
    )
    assert calls == [True, False]
    assert events.count("accept") == events.count("reject") == 1


@pytest.mark.parametrize("name", ["locals", "__zr_observe"])
def test_shadowed_plumbing_refused(name):
    with pytest.raises(UnsupportedBinding):
        generate_binding(
            profile(),
            {
                "native.py": SOURCE.replace(
                    "    details = {}", f"    {name} = 7\n    details = {{}}"
                )
            },
        )


def test_no_opaque_checkers_or_undeclared_predicate():
    p = profile()
    p["checker"] = "arbitrary_python_callback"
    with pytest.raises(InvalidEvidence):
        validate_profile(p)
    p = profile()
    p["rules"][1]["operator"] = "eval_python"
    with pytest.raises(InvalidEvidence):
        validate_profile(p)


def test_native_timeout_does_not_enter_acceptance_path():
    p = profile()
    source = SOURCE.replace("assert value", "raise TimeoutError()")
    # A changed native checking region needs a newly declared profile; this is
    # an exposed control and cannot earn unchanged transfer credit.
    for name in ["accept", "reject"]:
        p["sites"][name]["anchor"] = p["sites"][name]["anchor"].replace(
            "assert value", "raise TimeoutError()"
        )
    b = generate_binding(p, {"native.py": source})
    events = []
    scope = {"__zr_observe": lambda site, state: events.append(site)}
    exec(b["transformed"]["native.py"], scope)
    with pytest.raises(TimeoutError):
        scope["evaluate"]("r", "c", "base", 1, [True])
    assert events == []


@pytest.mark.parametrize(
    "grade,expected",
    [
        ("PASS", "CONFORMS"),
        ("FAIL", "VIOLATION"),
        ("TIMEOUT", "INCONCLUSIVE"),
        ("unknown", "UNSUPPORTED"),
    ],
)
def test_native_aggregate_status_mapping(grade, expected):
    items = list(execute([True]))
    p, binding, case, events, health, outcome = items
    p["facts"]["aggregate"]["accepted"] = "str"
    r = p["rules"][-1]
    r["target_mapping"] = {
        "true": ["PASS"],
        "false": ["FAIL"],
        "incomplete": ["TIMEOUT"],
    }
    next(e for e in events if e["kind"] == "aggregate")["values"]["accepted"] = grade
    result = evaluate(p, case, events, health, binding["sha256"])
    assert (
        next(r for r in result["records"] if r["relationship"] == "aggregate-derived")[
            "status"
        ]
        == expected
    )


def test_rehashed_manual_binding_change_is_not_mechanical_generation():
    from zerorun_harness.api import digest
    from zerorun_harness.binding import validate_binding
    from zerorun_harness.declarative import seal
    import hashlib

    p = profile()
    binding = generate_binding(p, {"native.py": SOURCE})
    binding["transformed"]["native.py"] = SOURCE
    binding["transformed_sources"]["native.py"] = hashlib.sha256(
        SOURCE.encode()
    ).hexdigest()
    binding = seal({k: v for k, v in binding.items() if k != "sha256"})
    assert digest(p) == binding["policy_sha256"]
    with pytest.raises(InvalidEvidence, match="mechanically regenerated"):
        validate_binding(p, binding)


def test_missing_producer_health_cannot_qualify_absence():
    items = execute([True])
    items[4]["transport"] = {"999": True}
    with pytest.raises(InvalidEvidence, match="Missing native producer"):
        assess(items)


@pytest.mark.parametrize(
    "values,omit,corrupt,coverage,transport,complete",
    itertools.product(
        list(itertools.product([True, False], repeat=2)),
        [False, True],
        [False, True],
        [False, True],
        [False, True],
        [False, True],
    ),
)
def test_ordinary_semantic_crosscheck(
    values, omit, corrupt, coverage, transport, complete
):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "ordinary_relationships",
        Path(__file__).resolve().parents[1] / "ordinary/relationships.py",
    )
    ordinary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ordinary)
    items = execute(values, omit=omit, corrupt=corrupt)
    p, _, case, events, health, _ = items
    health["sites"]["commit"] = coverage
    health["transport"] = {k: transport for k in health["transport"]}
    health["native_complete"] = {k: complete for k in health["native_complete"]}
    rows = assess(items)["records"]
    actual = [
        (
            r["relationship"],
            tuple(
                r["identity"][k]
                for k in next(x for x in p["rules"] if x["id"] == r["relationship"])[
                    "keys"
                ]
            ),
            r["status"],
        )
        for r in rows
    ]
    assert actual == ordinary.run(p, case, events, health)
