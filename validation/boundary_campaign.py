# SPDX-License-Identifier: MIT
"""Deterministic public-API boundary campaign. Executes no candidate programs.

Mutations are software controls, not new benchmark observations. The ordinary
route shares the written specification but imports no production semantic code.
"""

import copy
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ordinary"))
from qualification import qualify
from zerorun_harness import audit, capture, compare, export, report
from zerorun_harness.api import InvalidEvidence, profiles

spec = importlib.util.spec_from_file_location(
    "boundary_controls", ROOT / "tests/test_boundary_regressions.py"
)
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
full_spec = importlib.util.spec_from_file_location(
    "full_native_controls", ROOT / "tests/test_native_comparison.py"
)
full_controls = importlib.util.module_from_spec(full_spec)
full_spec.loader.exec_module(full_controls)

VALUES = [
    None,
    False,
    True,
    -1,
    0,
    1,
    2,
    0.0,
    1.0,
    "",
    "accept",
    "terminal",
    "PASSED",
    [],
    {},
    [True],
    [False, True],
    {"native_complete": True},
    {"kind": "accept", "index": 0},
    {"x": "PASSED"},
]


def paths(node, prefix=()):
    yield prefix
    if type(node) is dict:
        for key in sorted(node):
            yield from paths(node[key], prefix + (key,))
    elif type(node) is list:
        for i, item in enumerate(node):
            yield from paths(item, prefix + (i,))


def replace(node, path, value):
    if not path:
        return copy.deepcopy(value)
    result = copy.deepcopy(node)
    cursor = result
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = copy.deepcopy(value)
    return result


def run():
    start = time.perf_counter()
    policy = {k: v["source_sha256"] for k, v in profiles().items()}
    ev = controls.record()
    sw = copy.deepcopy(ev)
    sw["family"] = "swe"
    sw["provenance"]["source_sha256"] = policy["swe"][0]
    sw["observation"] = dict(
        source_sha256=policy["swe"][0],
        found=True,
        observer_coverage=True,
        parser_calls=[{}, {"x": "PASSED"}],
        selected={"x": "PASSED"},
    )
    sw["native_reference"] = {"selected": {"x": "PASSED"}}
    totals = Counter()
    for base in [ev, sw, full_controls.row()]:
        for field in ["observation", "native_reference"]:
            for path in paths(base[field]):
                for value in VALUES:
                    r = copy.deepcopy(base)
                    r[field] = replace(base[field], path, value)
                    totals["cases"] += 1
                    try:
                        bundle = capture({"records": [r]})
                    except InvalidEvidence:
                        assert type(r["observation"]) is not dict or (
                            r["native_reference"] is not None
                            and type(r["native_reference"]) is not dict
                        )
                        totals["envelope_rejected"] += 1
                        continue
                    before = copy.deepcopy(bundle)
                    actual = audit(bundle)["records"][0]
                    expected = qualify(r, policy)
                    assert all(actual[k] == v for k, v in expected.items()), (
                        field,
                        path,
                        value,
                        actual,
                        expected,
                    )
                    exported = export(bundle)["records"][0]
                    assert exported["qualification"] == actual["status"]
                    assert (
                        exported["independent_native_reference"]
                        == r["native_reference"]
                    )
                    assert (
                        compare(bundle, bundle)["records"][0]["same_evidence"] is True
                    )
                    assert actual["status"] + ": 1" in report(bundle)
                    assert bundle == before
                    # Diagnostic labels are not semantic premises.
                    labelled = copy.deepcopy(r)
                    labelled["observation"].update(expected="PASS", verdict="CONFORMS")
                    rerun = audit(capture({"records": [labelled]}))["records"][0]
                    for key in ["status", "relationship_status", "native_agreement"]:
                        assert actual[key] == rerun[key]
                    totals["audited"] += 1
                    totals[actual["status"]] += 1
    return dict(
        passed=True,
        counts=dict(totals),
        values_per_path=len(VALUES),
        candidate_calls=0,
        elapsed_seconds=time.perf_counter() - start,
        scope="Deterministic software boundary mutations; not independent native observations",
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
