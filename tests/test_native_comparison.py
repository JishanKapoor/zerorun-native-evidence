# SPDX-License-Identifier: MIT
"""Independent assertions about complete supplied values and comparable identity."""

import copy
import pytest
from zerorun_harness import audit, capture, compare, export
from zerorun_harness.api import native_agreement, profiles


def row():
    source = profiles()["swe"]["source_sha256"][0]
    grading = {
        k: {"success": ["x"] if k == "FAIL_TO_PASS" else [], "failure": []}
        for k in ["FAIL_TO_PASS", "PASS_TO_PASS", "FAIL_TO_FAIL", "PASS_TO_FAIL"]
    }
    return dict(
        id="task-A",
        family="swe",
        provenance=dict(
            source_sha256=source, input_sha256="1" * 64, candidate_sha256="2" * 64
        ),
        observation=dict(
            source_sha256=source,
            found=True,
            observer_coverage=True,
            parser_calls=[{"x": "PASSED"}],
            selected={"x": "PASSED"},
            native_report=grading,
            native_resolution="RESOLVED_FULL",
        ),
        native_reference=dict(
            selected={"x": "PASSED"},
            found=True,
            report=copy.deepcopy(grading),
            resolution="RESOLVED_FULL",
        ),
    )


@pytest.mark.parametrize("change", ["found", "report", "resolution"])
def test_disagreement_outside_selected_map_is_not_preservation(change):
    r = row()
    if change == "found":
        r["native_reference"]["found"] = False
    if change == "report":
        r["native_reference"]["report"]["FAIL_TO_PASS"]["success"] = []
    if change == "resolution":
        r["native_reference"]["resolution"] = "RESOLVED_NO"
    assert native_agreement(r) is False
    result = audit(capture({"records": [r]}))["records"][0]
    assert result["relationship_status"] == "CONFORMS"
    assert result["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("found", 1),
        ("found", None),
        ("report", {}),
        ("report", {"FAIL_TO_PASS": {"success": [True], "failure": []}}),
        ("resolution", True),
        ("resolution", "FULL"),
        ("resolution", None),
    ],
)
def test_invalid_supplied_native_field_is_not_agreement(field, value):
    r = row()
    r["native_reference"][field] = value
    assert native_agreement(r) is None
    result = audit(capture({"records": [r]}))["records"][0]
    assert result["status"] == "INCONCLUSIVE"
    assert "independent_native_reference_unassessable" in result["reasons"]


@pytest.mark.parametrize("field", ["found", "native_report", "native_resolution"])
def test_missing_observed_counterpart_is_not_agreement(field):
    r = row()
    del r["observation"][field]
    assert native_agreement(r) is None


def test_minimal_native_map_remains_explicitly_scoped():
    r = row()
    r["native_reference"] = {"selected": {"x": "PASSED"}}
    actual = audit(capture({"records": [r]}))["records"][0]
    assert actual["native_agreement"] is True
    assert actual["native_agreement_fields"] == ["selected"]


def test_full_native_scope_is_recorded():
    actual = audit(capture({"records": [row()]}))["records"][0]
    assert actual["native_agreement_fields"] == [
        "selected",
        "found",
        "report",
        "resolution",
    ]


@pytest.mark.parametrize("field", ["candidate_sha256", "input_sha256"])
def test_reused_record_id_does_not_hide_changed_scientific_input(field):
    left = row()
    right = copy.deepcopy(left)
    right["provenance"][field] = "3" * 64
    result = compare(capture({"records": [left]}), capture({"records": [right]}))
    assert result["schema"] == "zerorun-compare/2"
    r = result["records"][0]
    assert r["identity_alignment"] == "MISMATCH"
    assert r["identity_mismatches"] == [field]
    assert r["left_status"] == r["right_status"] == "CONFORMS"


def test_source_change_is_not_an_input_identity_change():
    left = row()
    right = copy.deepcopy(left)
    source = profiles()["swe"]["source_sha256"][1]
    right["provenance"]["source_sha256"] = source
    right["observation"]["source_sha256"] = source
    r = compare(capture({"records": [left]}), capture({"records": [right]}))["records"][
        0
    ]
    assert r["identity_alignment"] == "MATCHED"
    assert r["identity_mismatches"] == [] and r["same_evidence"] is False


def test_missing_record_keeps_explicit_alignment():
    r = row()
    other = copy.deepcopy(r)
    other["id"] = "other"
    result = compare(capture({"records": [r]}), capture({"records": [other]}))
    assert len(result["records"]) == 2
    assert all(v["identity_alignment"] == "MISSING" for v in result["records"])


def test_export_preserves_complete_supplied_native_fields():
    original = row()
    bundle = capture({"records": [original]})
    result = export(bundle)
    assert result["schema"] == "zerorun-native-export/2"
    native = result["records"][0]["native_fields"]
    assert native == original["native_reference"]
    native["report"]["FAIL_TO_PASS"]["success"].clear()
    assert bundle["records"][0]["observation"]["native_report"]["FAIL_TO_PASS"][
        "success"
    ] == ["x"]


def test_comparison_reports_family_and_multiple_identity_mismatches():
    left = row()
    right = copy.deepcopy(left)
    right["family"] = "evalplus"
    right["provenance"]["input_sha256"] = "3" * 64
    right["provenance"]["candidate_sha256"] = "4" * 64
    r = compare(capture({"records": [left]}), capture({"records": [right]}))["records"][
        0
    ]
    assert r["identity_alignment"] == "MISMATCH"
    assert r["identity_mismatches"] == ["family", "input_sha256", "candidate_sha256"]
