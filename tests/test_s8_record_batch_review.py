"""Independent native stored identity, acquisition and C2 handoff controls."""
import asyncio
import copy
import sys
from types import ModuleType

import pytest

from zerorun_harness.api import InvalidEvidence, digest
from zerorun_harness.batches import extract_batches
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.declarative import evaluate
from zerorun_harness.records import register_records
from test_activation_binding import prepared as activation_prepared
from test_record_batches import MODEL, capture, setup_profile


HANDOFF = '''def outer(scores, mode):
    committed = []
    for score in scores:
        committed.append(score)
    if mode == 'empty':
        native = []
    elif mode == 'reverse':
        native = committed[::-1]
    elif mode == 'duplicate':
        native = [committed[0], committed[0]]
    elif mode == 'short':
        native = committed[:1]
    else:
        native = committed[:]
    returned = native
    return returned
'''


def handoff(monkeypatch, mode="normal"):
    profile = setup_profile()
    batch = profile["sites"]["return"]
    batch.update(anchor="returned = native", kind="consumer")
    batch["batch"]["local"] = "returned"
    commit = copy.deepcopy(batch)
    del commit["batch"]
    commit.update(anchor="committed.append(score)", kind="raw")
    for spec in commit["projection"].values():
        if "item" in spec:
            del spec["item"]
            spec["local"] = "score"
    profile["sites"]["commit"] = commit
    profile["facts"]["consumer"] = {"flag": "int"}
    profile["rules"][0].update(check="C2", consumer="consumer", source_field="flag",
                                target_field="flag", operator="identity", requires=["commit", "return"])
    binding = generate_binding(profile, {"native.py": HANDOFF, "native_model.py": MODEL}, grammar_version="1.3.0")
    module = ModuleType("native_model")
    exec(MODEL, module.__dict__)
    monkeypatch.setitem(sys.modules, "native_model", module)
    registry = register_records(profile, binding, {"score": module.Score})
    raw = []

    class Sink:
        def emit(self, event):
            raw.append(copy.deepcopy(event))
            return True

    scope = {"__zr_observe": recorder(profile, binding, Sink(), 123, records=registry)}
    exec(binding["transformed"]["native.py"], scope)
    inputs = [module.Score("alpha", 1), module.Score("beta", 0)]
    result = scope["outer"](inputs, mode)
    original_scope = {}
    exec(HANDOFF, original_scope)
    assert result == original_scope["outer"](inputs, mode)
    case = dict(id="authored-record-C2", version="1", source_sha256=digest(binding["original_sources"]),
                input_sha256=digest([["alpha", 1], ["beta", 0]]),
                inventory=[dict(run="r", candidate="c", obligation=0, phase="b", attempt=1, sample_id=name)
                           for name in ("alpha", "beta")])
    health = dict(binding_sha256=binding["sha256"], sites={site: True for site in profile["sites"]},
                  transport={"123": True}, native_complete={profile["rules"][0]["id"]: True},
                  qualification_sha256="1" * 64)
    return profile, binding, case, raw, health


def classify(parts):
    profile, binding, case, raw, health = parts
    acquired = extract_batches(profile, binding, raw)
    output = evaluate(profile, case, acquired["events"], health, binding["sha256"])
    return {row["identity"]["sample_id"]: row["status"] for row in output["records"]}, acquired


@pytest.mark.parametrize("mode", ["normal", "reverse"])
def test_actual_commitment_to_batch_C2_uses_sample_identity_not_list_position(monkeypatch, mode):
    rows, acquired = classify(handoff(monkeypatch, mode))
    assert rows == {"alpha": "CONFORMS", "beta": "CONFORMS"}
    consumer = [event for event in acquired["events"] if event["kind"] == "consumer"]
    assert [event["acquisition"]["ordinal"] for event in consumer] == [0, 1]
    assert [event["identity"]["sample_id"] for event in consumer] == (
        ["alpha", "beta"] if mode == "normal" else ["beta", "alpha"])


@pytest.mark.parametrize("mode,expected", [
    ("empty", {"alpha": "INCONCLUSIVE", "beta": "INCONCLUSIVE"}),
    ("short", {"alpha": "CONFORMS", "beta": "INCONCLUSIVE"}),
    ("duplicate", {"alpha": "INCONCLUSIVE", "beta": "INCONCLUSIVE"}),
])
def test_C2_empty_short_or_duplicate_population_never_invents_missing_value(monkeypatch, mode, expected):
    rows, acquired = classify(handoff(monkeypatch, mode))
    assert rows == expected
    assert acquired["batches"][0]["complete"] is True  # Physical acquisition only.


def test_dropped_item_is_incomplete_and_missing_sample_value_stays_unknown(monkeypatch):
    parts = handoff(monkeypatch)
    raw = parts[3]
    raw[:] = [event for event in raw if not (event.get("kind") == "consumer"
               and event["identity"]["sample_id"] == "beta")]
    rows, acquired = classify(parts)
    assert rows == {"alpha": "CONFORMS", "beta": "INCONCLUSIVE"}
    assert acquired["batches"][0]["complete"] is False


def test_lost_end_cannot_certify_population_but_retained_C2_values_survive(monkeypatch):
    parts = handoff(monkeypatch)
    raw = parts[3]
    raw[:] = [event for event in raw if event.get("stage") != "end"]
    rows, acquired = classify(parts)
    assert acquired["batches"][0]["complete"] is False
    assert rows == {"alpha": "CONFORMS", "beta": "CONFORMS"}
    # Independent transport loss is a separate premise, not guessed from absence.
    parts[4]["transport"]["123"] = False
    assert classify(parts)[0] == {"alpha": "INCONCLUSIVE", "beta": "INCONCLUSIVE"}


def test_wrong_retained_value_remains_a_witness_despite_lost_end(monkeypatch):
    parts = handoff(monkeypatch)
    raw = parts[3]
    raw[:] = [event for event in raw if event.get("stage") != "end"]
    next(event for event in raw if event.get("kind") == "consumer")["values"]["flag"] = 0
    parts[4]["transport"]["123"] = False
    rows, acquired = classify(parts)
    assert rows == {"alpha": "VIOLATION", "beta": "INCONCLUSIVE"}
    assert acquired["batches"][0]["complete"] is False


@pytest.mark.parametrize("damage", ["batch-bool", "batch-foreign", "ordinal-bool", "ordinal-negative", "ordinal-cap", "group-foreign"])
def test_malformed_acquisition_cannot_create_complete_native_population(monkeypatch, damage):
    profile, binding, raw = capture(monkeypatch, [("alpha", 1), ("beta", 0)])
    event = raw[1]
    if damage == "batch-bool":
        event["acquisition"]["batch"] = True
    elif damage == "batch-foreign":
        event["acquisition"]["batch"] += 1
    elif damage == "ordinal-bool":
        event["acquisition"]["ordinal"] = False
    elif damage == "ordinal-negative":
        event["acquisition"]["ordinal"] = -1
    elif damage == "ordinal-cap":
        event["acquisition"]["ordinal"] = 64
    else:
        event["identity"]["candidate"] = "foreign"
    with pytest.raises(InvalidEvidence):
        extract_batches(profile, binding, raw)


def test_distinct_producer_batches_cannot_steal_acquisition_elements(monkeypatch):
    profile, binding, left = capture(monkeypatch, [("alpha", 1), ("beta", 0)])
    right = copy.deepcopy(left)
    for event in right:
        event["producer"] = 456
        if "id" in event:
            event["id"] = "456:" + str(event["seq"])
    raw = [item for pair in zip(left, right) for item in pair]
    acquired = extract_batches(profile, binding, raw)
    assert len(acquired["batches"]) == 2 and all(row["complete"] for row in acquired["batches"])
    raw[2]["producer"] = 789
    with pytest.raises(InvalidEvidence):
        extract_batches(profile, binding, raw)


def test_cancelled_activation_after_commit_never_attaches_later_call(monkeypatch):
    source = '''async def outer(n, gate, state):
    try:
        value = n
        await gate.wait()
        state.append(value)
    finally:
        state.append('cleanup')
'''
    _, _, events, _, scope = activation_prepared(source)

    async def run():
        gate = asyncio.Event()
        state = []
        task = asyncio.create_task(scope["outer"](7, gate, state))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.set()
        await scope["outer"](8, gate, state)
        return state

    assert asyncio.run(run()) == ["cleanup", 8, "cleanup"]
    assert [(event["values"]["flag"], event["identity"]["obligation"]) for event in events] == [(7, 1), (8, 2)]


@pytest.mark.parametrize("reserved", [
    "except Exception as __zr_activation:\n        pass",
    "except* Exception as __zr_activation:\n        pass",
])
def test_activation_exception_binding_names_refused(reserved):
    source = "def outer(n):\n    try:\n        pass\n    " + reserved + "\n    value = n\n"
    with pytest.raises(InvalidEvidence):
        activation_prepared(source)


def test_enter_scope_rejects_hostile_string_without_hash_or_comparison():
    _, _, events, callback, _ = activation_prepared("def outer(n):\n value = n\n return value\n")
    calls = []

    class Scope(str):
        def __eq__(self, other):
            calls.append("eq")
            return True

        def __hash__(self):
            calls.append("hash")
            return 1

    assert callback.enter(Scope("native.py:outer")) is None
    assert calls == [] and len(events) == 1 and type(events[0]) is object
