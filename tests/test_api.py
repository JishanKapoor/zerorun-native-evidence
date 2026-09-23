# SPDX-License-Identifier: MIT
import copy, json
from importlib.resources import files
import pytest
from zerorun_harness import capture, audit, compare, export, report
from zerorun_harness.api import InvalidEvidence, canonical
from zerorun_harness.cli import main, read


@pytest.fixture
def manifest():
    return json.loads(
        files("zerorun_harness")
        .joinpath("examples/development-manifest.json")
        .read_text()
    )


def test_complete_five_operations(manifest):
    b = capture(manifest)
    a = audit(b)
    e = export(b)
    r = report(b)
    c = compare(b, b)
    assert len(a["records"]) == len(e["records"]) == len(c["records"]) == 9
    assert a["counts"] == {"CONFORMS": 7, "INCONCLUSIVE": 1, "VIOLATION": 1}
    assert all(v["same_evidence"] for v in c["records"])
    assert "Records: 9" in r and "VIOLATION: 1" in r
    assert capture(manifest) == b and report(b) == r


def test_capture_isolated_from_mutation(manifest):
    b = capture(manifest)
    manifest["records"][0]["observation"].clear()
    assert b["records"][0]["observation"]


def test_export_isolated_from_mutation(manifest):
    b = capture(manifest)
    e = export(b)
    e["records"][0]["native_state"].clear()
    audit(b)


def test_integrity_tamper(manifest):
    b = capture(manifest)
    b["records"][0]["id"] = "tampered"
    with pytest.raises(InvalidEvidence, match="digest"):
        audit(b)


def test_duplicate_identity(manifest):
    manifest["records"].append(copy.deepcopy(manifest["records"][0]))
    with pytest.raises(InvalidEvidence, match="duplicate"):
        capture(manifest)


@pytest.mark.parametrize("value", [None, True, {}, [], 1, "bad"])
def test_invalid_record(value):
    with pytest.raises(InvalidEvidence):
        capture({"records": [value]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", ""),
        ("id", 4),
        ("family", "unknown"),
        ("family", None),
        ("provenance", {}),
        ("observation", None),
        ("native_reference", []),
    ],
)
def test_manifest_field_schema(manifest, field, value):
    manifest["records"][0][field] = value
    with pytest.raises(InvalidEvidence):
        capture(manifest)


def test_unknown_pinned_source(manifest):
    r = manifest["records"][0]
    r["provenance"]["source_sha256"] = "0" * 64
    r["observation"]["source_sha256"] = "0" * 64
    assert audit(capture(manifest))["records"][0]["status"] == "UNSUPPORTED"


def test_source_association_mismatch(manifest):
    manifest["records"][0]["observation"]["source_sha256"] = "0" * 64
    assert audit(capture(manifest))["records"][0]["status"] == "UNSUPPORTED"


def test_missing_population_preserved(manifest):
    a = capture(manifest)
    manifest["records"].pop()
    b = capture(manifest)
    rows = compare(a, b)["records"]
    assert len(rows) == 9 and sum(r["right_status"] == "MISSING" for r in rows) == 1


def test_native_reference_is_separate(manifest):
    m = {"records": [manifest["records"][1]]}
    m["records"][0]["native_reference"] = {"grade": "pass", "details": [True, True]}
    a = audit(capture(m))["records"][0]
    assert (
        a["status"] == "INCONCLUSIVE"
        and a["relationship_status"] == "CONFORMS"
        and a["native_agreement"] is False
    )


def test_native_export_never_substitutes_verdict(manifest):
    b = capture(manifest)
    e = export(b)
    assert e["records"][0]["qualification"] == "VIOLATION"
    assert e["records"][0]["native_state"] == b["records"][0]["observation"]["state"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json(value):
    with pytest.raises(InvalidEvidence):
        canonical({"v": value})


@pytest.mark.parametrize("value", [{1: "x"}, {"x": (1, 2)}, {"x": {False: "y"}}])
def test_python_nonjson_types_refused(value):
    with pytest.raises(InvalidEvidence):
        canonical(value)


def test_duplicate_json_keys_refused(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"x":1,"x":2}')
    with pytest.raises(InvalidEvidence):
        read(p)


def test_cycle_and_deep_json_refused():
    cycle = []
    cycle.append(cycle)
    with pytest.raises(InvalidEvidence, match="Cyclic"):
        canonical(cycle)
    tree = []
    cursor = tree
    for _ in range(66):
        child = []
        cursor.append(child)
        cursor = child
    with pytest.raises(InvalidEvidence, match="nesting"):
        canonical(tree)


def test_shared_subobject_is_json():
    value = {"x": 1}
    assert canonical([value, value]) == b'[{"x":1},{"x":1}]'


def test_nonfinite_cli_refused(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"x":NaN}')
    with pytest.raises(InvalidEvidence):
        read(p)


def test_cli_all_operations(tmp_path, manifest):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(manifest))
    b = tmp_path / "capture.json"
    assert main(["capture", str(source), "--output", str(b)]) == 0
    for op in ["audit", "export", "report"]:
        assert main([op, str(b), "--output", str(tmp_path / (op + ".json"))]) == 0
    assert (
        main(["compare", str(b), str(b), "--output", str(tmp_path / "compare.json")])
        == 0
    )
    original = b.read_bytes()
    assert main(["capture", str(source), "--output", str(b)]) == 2
    assert b.read_bytes() == original


def test_cli_unknown_input_and_digest_errors(tmp_path):
    assert (
        main(["audit", str(tmp_path / "missing"), "--output", str(tmp_path / "out")])
        == 2
    )
    p = tmp_path / "bad"
    p.write_text("{}")
    assert main(["audit", str(p), "--output", str(tmp_path / "out")]) == 2


def test_report_identity_escaped(manifest):
    manifest["records"][0]["id"] = "identity\nwith\ttabs"
    out = report(capture(manifest))
    assert "identity\\nwith\\ttabs" in out
