# SPDX-License-Identifier: MIT
import copy, importlib.util, itertools, random
from pathlib import Path
import pytest
from zerorun_harness import checks

spec = importlib.util.spec_from_file_location(
    "independent_ordinary", Path(__file__).resolve().parents[1] / "ordinary/checks.py"
)
ordinary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ordinary)


def observation(values=(True, False), details=None, progress=None, status=0):
    values = list(values)
    details = values[:] if details is None else list(details)
    return {
        "source_sha256": "a" * 64,
        "events": [
            {
                "seq": i + 1,
                "index": i,
                "kind": "accept" if v else "reject",
                "optimize": 0,
            }
            for i, v in enumerate(values)
        ],
        "seals": [
            {
                "seal": True,
                "attempted": len(values),
                "emitted": len(values),
                "dropped": 0,
            }
        ],
        "state": {
            "progress": len(values) if progress is None else progress,
            "details": details,
            "worker_status": status,
        },
        "health": {
            "native_complete": True,
            "transport_intact": True,
            "semantic_coverage": True,
        },
        "exitcode": 0,
        "outer_timeout": False,
    }


def both(data, expected, family="evalplus"):
    assert getattr(ordinary, family)(data) == expected
    assert getattr(checks, family)(data) == expected


def test_exhaustive_boolean_commitment_space():
    count = 0
    for n in range(1, 5):
        for values in itertools.product([False, True], repeat=n):
            for stored in itertools.product([False, True], repeat=n):
                for progress in range(n + 1):
                    for status in [0, 1]:
                        expected = (
                            "CONFORMS"
                            if progress == n and stored == values
                            else "VIOLATION"
                        )
                        both(observation(values, stored, progress, status), expected)
                        count += 1
    assert count == 3184


@pytest.mark.parametrize(
    "health",
    [
        None,
        {},
        [],
        True,
        {"native_complete": True},
        dict(
            native_complete=True,
            transport_intact=True,
            semantic_coverage=True,
            extra=True,
        ),
    ],
)
def test_invalid_health(health):
    o = observation()
    o["health"] = health
    both(o, "INCONCLUSIVE")


@pytest.mark.parametrize(
    "key", ["native_complete", "transport_intact", "semantic_coverage"]
)
@pytest.mark.parametrize("value", [False, 0, 1, None, "true", [], {}])
def test_health_is_typed(key, value):
    o = observation()
    o["health"][key] = value
    both(o, "INCONCLUSIVE")


@pytest.mark.parametrize("value", [False, True, None, "0", 1, 137, -9])
def test_process_exit_is_typed(value):
    o = observation()
    o["exitcode"] = value
    both(o, "INCONCLUSIVE")


@pytest.mark.parametrize("value", [None, 1, 0, "false", True])
def test_timeout_is_boolean(value):
    o = observation()
    o["outer_timeout"] = value
    both(o, "INCONCLUSIVE")


@pytest.mark.parametrize("value", [None, True, -1, 3, 1.0, "1"])
def test_invalid_progress(value):
    o = observation()
    o["state"]["progress"] = value
    both(o, "UNSUPPORTED")


@pytest.mark.parametrize("value", [None, False, "0", 2, 3, -1])
def test_uncommitted_native_status(value):
    o = observation()
    o["state"]["worker_status"] = value
    both(o, "INCONCLUSIVE")


@pytest.mark.parametrize(
    "change",
    [
        "drop",
        "duplicate",
        "reorder",
        "seq",
        "optimize",
        "kind",
        "index_bool",
        "index_float",
        "out_of_range",
    ],
)
def test_event_failures(change):
    o = observation()
    expected = "UNSUPPORTED"
    if change == "drop":
        o["events"].pop()
        expected = "INCONCLUSIVE"
    if change == "duplicate":
        o["events"][1]["index"] = 0
    if change == "reorder":
        o["events"][0]["index"] = 1
        o["events"][1]["index"] = 0
    if change == "seq":
        o["events"][0]["seq"] = 2
        expected = "INCONCLUSIVE"
    if change == "optimize":
        o["events"][0]["optimize"] = 1
    if change == "kind":
        o["events"][0]["kind"] = "unknown"
    if change == "index_bool":
        o["events"][0]["index"] = False
    if change == "index_float":
        o["events"][0]["index"] = 0.0
    if change == "out_of_range":
        o["events"][0]["index"] = 2
    both(o, expected)


@pytest.mark.parametrize("key", ["seal", "attempted", "emitted", "dropped"])
@pytest.mark.parametrize("value", [None, False, True, "0", -1, 3])
def test_seal_types_and_counts(key, value):
    o = observation()
    o["seals"][0][key] = value
    if key == "seal" and value is True:
        both(o, "CONFORMS")
    else:
        both(o, "INCONCLUSIVE")


def test_valid_early_exit():
    o = observation([True, False], [True, False, False, False], 2, 1)
    both(o, "CONFORMS")


def test_empty_observation_is_not_success():
    both(observation([]), "INCONCLUSIVE")


def test_native_prefix_longer_than_trace_is_observation_gap():
    both(observation([True], [True, True], 2), "INCONCLUSIVE")


def test_missing_commit_is_distinct_from_missing_dispositions():
    both(observation([True, True], [True, False], 1), "VIOLATION")


def test_verdict_corruption_irrelevant():
    o = observation()
    o.update(
        pycontract_status="VIOLATION",
        ordinary_equal_evidence_status="VIOLATION",
        expected="FAIL",
    )
    both(o, "CONFORMS")


def test_primitive_state_types():
    o = observation()
    o["state"]["details"] = [1, 0]
    both(o, "UNSUPPORTED")


def test_source_shape():
    o = observation()
    o["source_sha256"] = "unknown"
    both(o, "UNSUPPORTED")


def test_swe_all_native_statuses():
    for status in ["PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL"]:
        o = {
            "found": True,
            "observer_coverage": True,
            "parser_calls": [{"x": status}],
            "selected": {"x": status},
        }
        both(o, "CONFORMS", "swe")


def test_swe_selected_fallback():
    o = {
        "found": True,
        "observer_coverage": True,
        "parser_calls": [{}, {"x": "PASSED"}],
        "selected": {"x": "PASSED"},
    }
    both(o, "CONFORMS", "swe")
    o["selected"] = {}
    both(o, "VIOLATION", "swe")


@pytest.mark.parametrize(
    "value", [None, [], {"x": True}, {"x": "XPASS"}, {1: "PASSED"}]
)
def test_swe_invalid_maps(value):
    o = {
        "found": True,
        "observer_coverage": True,
        "parser_calls": [{"x": "PASSED"}],
        "selected": value,
    }
    both(o, "UNSUPPORTED", "swe")


def test_swe_empty_selected_is_valid_when_parser_returned_empty():
    both(
        {
            "found": True,
            "observer_coverage": True,
            "parser_calls": [{}],
            "selected": {},
        },
        "CONFORMS",
        "swe",
    )


def test_deterministic_malformed_object_fuzz():
    rng = random.Random(20260922)
    pool = [None, False, True, 0, 1, -1, 0.0, "", [], {}, ["x"], {"x": None}]
    for _ in range(2000):
        o = observation()
        key = rng.choice(list(o))
        o[key] = copy.deepcopy(rng.choice(pool))
        assert checks.evalplus(o) == ordinary.evalplus(o)
        s = {
            "found": True,
            "observer_coverage": True,
            "parser_calls": [{}],
            "selected": {},
        }
        s[rng.choice(list(s))] = copy.deepcopy(rng.choice(pool))
        assert checks.swe(s) == ordinary.swe(s)
