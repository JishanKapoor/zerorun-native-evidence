# SPDX-License-Identifier: MIT
"""Public-boundary regressions identified after the first release validation."""

import copy
import json
from importlib.resources import files

import pytest

from zerorun_harness import audit, capture, compare, export, report
from zerorun_harness.api import native_agreement, profiles


def record():
    source = profiles()["evalplus"]["source_sha256"][0]
    return {
        "id": "boundary-control",
        "family": "evalplus",
        "provenance": {
            "source_sha256": source,
            "input_sha256": "1" * 64,
            "candidate_sha256": "2" * 64,
        },
        "observation": {
            "source_sha256": source,
            "health": dict(
                native_complete=True, transport_intact=True, semantic_coverage=True
            ),
            "outer_timeout": False,
            "exitcode": 0,
            "events": [
                dict(seq=1, index=0, kind="accept", optimize=0),
                dict(seq=2, index=1, kind="reject", optimize=0),
            ],
            "seals": [dict(seal=True, attempted=2, emitted=2, dropped=0)],
            "state": dict(details=[True, False], progress=2, worker_status=0),
        },
        "native_reference": {"grade": "fail", "details": [True, False]},
    }


@pytest.mark.parametrize("health", [None, [], False, 1, "complete"])
def test_public_operations_handle_malformed_health(health):
    r = record()
    r["observation"]["health"] = health
    b = capture({"records": [r]})
    assert audit(b)["records"][0]["status"] == "INCONCLUSIVE"
    assert native_agreement(r) is None
    assert export(b)["records"][0]["qualification"] == "INCONCLUSIVE"
    assert compare(b, b)["records"][0]["same_evidence"] is True
    assert "INCONCLUSIVE: 1" in report(b)


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "accept"},
        {"kind": "accept", "index": 0},
        {"kind": "reject", "index": 0},
        {"kind": "terminal", "terminal": False},
    ],
)
def test_native_metadata_cannot_override_internal_terminal(extra):
    r = record()
    r["native_reference"] = None
    r["observation"]["state"]["details"][0] = False
    r["observation"]["state"].update(extra)
    a = audit(capture({"records": [r]}))["records"][0]
    assert a["relationship_status"] == "VIOLATION"
    assert a["status"] == "VIOLATION"


@pytest.mark.parametrize("cells", [[1, False], [True, 0], [True, None], [[], False]])
def test_reference_agreement_requires_primitive_boolean_cells(cells):
    r = record()
    r["observation"]["state"]["details"] = cells
    assert native_agreement(r) is None
    assert audit(capture({"records": [r]}))["records"][0]["status"] == "UNSUPPORTED"


@pytest.mark.parametrize("value", [None, True, 1, [], {}, "UNKNOWN"])
def test_swe_reference_requires_native_status_values(value):
    source = profiles()["swe"]["source_sha256"][0]
    r = record()
    r["family"] = "swe"
    r["provenance"]["source_sha256"] = source
    r["observation"] = dict(
        source_sha256=source,
        found=True,
        observer_coverage=True,
        parser_calls=[{"x": "PASSED"}],
        selected={"x": value},
    )
    r["native_reference"] = {"selected": {"x": value}}
    assert native_agreement(r) is None
    assert audit(capture({"records": [r]}))["records"][0]["status"] == "UNSUPPORTED"
