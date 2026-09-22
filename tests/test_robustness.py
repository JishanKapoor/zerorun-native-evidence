# SPDX-License-Identifier: MIT
import copy, json
from importlib.resources import files
import pytest
from zerorun_harness import capture, audit, export, compare
from zerorun_harness.api import (
    InvalidEvidence,
    canonical,
    digest,
    native_agreement,
    profiles,
)
from zerorun_harness import cli


def row():
    return json.loads(
        files("zerorun_harness")
        .joinpath("examples/development-manifest.json")
        .read_text()
    )["records"][5]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {"extra": 1},
        {"records": []},
        {"records": None},
        {"records": [{}] * 4097},
    ],
)
def test_capture_rejects_bad_envelopes(bad):
    with pytest.raises(InvalidEvidence):
        capture(bad)


@pytest.mark.parametrize(
    "key,value",
    [("schema", "future"), ("mode", "execute"), ("sha256", "x"), ("records", [])],
)
def test_bad_bundle(key, value):
    b = capture({"records": [row()]})
    b[key] = value
    with pytest.raises(InvalidEvidence):
        audit(b)


def test_bundle_extra_field_refused():
    b = capture({"records": [row()]})
    b["extra"] = 1
    with pytest.raises(InvalidEvidence):
        audit(b)


def test_invalid_provenance_and_reference():
    for k, v in [
        ("source_sha256", "A" * 64),
        ("input_sha256", True),
        ("candidate_sha256", ""),
    ]:
        r = row()
        r["provenance"][k] = v
        with pytest.raises(InvalidEvidence):
            capture({"records": [r]})
    r = row()
    r["id"] = "x" * 1025
    with pytest.raises(InvalidEvidence):
        capture({"records": [r]})


def test_swe_api_native_agreement():
    r = {
        "id": "swe-test",
        "family": "swe",
        "provenance": {
            "source_sha256": profiles()["swe"]["source_sha256"][0],
            "input_sha256": "1" * 64,
            "candidate_sha256": "2" * 64,
        },
        "observation": {
            "source_sha256": profiles()["swe"]["source_sha256"][0],
            "found": True,
            "observer_coverage": True,
            "parser_calls": [{"x": "XFAIL"}],
            "selected": {"x": "XFAIL"},
        },
        "native_reference": {"selected": {"x": "XFAIL"}},
    }
    assert audit(capture({"records": [r]}))["records"][0]["native_agreement"] is True
    r["native_reference"]["selected"] = {}
    assert audit(capture({"records": [r]}))["records"][0]["native_agreement"] is False
    r["native_reference"] = {}
    assert native_agreement(r) is None
    assert export(capture({"records": [r]}))["records"][0]["native_state"] == {
        "x": "XFAIL"
    }


@pytest.mark.parametrize(
    "ref",
    [
        {},
        {"grade": "unknown", "details": []},
        {"grade": "pass", "details": [1]},
        {"grade": "pass", "details": "bad"},
    ],
)
def test_bad_native_reference_diagnostic(ref):
    r = row()
    r["native_reference"] = ref
    assert native_agreement(r) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", None),
        ("state", {"details": [], "progress": True}),
        ("state", {"details": [], "progress": 0, "worker_status": 2}),
    ],
)
def test_bad_native_state_diagnostic(field, value):
    r = row()
    r["native_reference"] = {"grade": "pass", "details": []}
    r["observation"][field] = value
    assert native_agreement(r) is None


def test_incomplete_native_diagnostic():
    r = row()
    r["native_reference"] = {"grade": "pass", "details": []}
    r["observation"]["health"]["native_complete"] = False
    assert native_agreement(r) is None


def test_nonutf8_and_oversized_cli(tmp_path, monkeypatch):
    p = tmp_path / "bad"
    p.write_bytes(b"\xff")
    with pytest.raises(InvalidEvidence):
        cli.read(p)
    p.write_bytes(b"0" * 65)
    monkeypatch.setattr(cli, "MAX_BYTES", 64)
    with pytest.raises(InvalidEvidence, match="64 MiB"):
        cli.read(p)


def test_cli_deep_json(tmp_path):
    p = tmp_path / "deep"
    p.write_text("[" * 2000 + "]" * 2000)
    with pytest.raises(InvalidEvidence):
        cli.read(p)


def test_reject_unserializable_and_surrogate():
    for v in [object(), {"v": set()}, {"v": b"bytes"}, {"v": "\ud800"}]:
        with pytest.raises(InvalidEvidence):
            canonical(v)


def test_shared_dictionary_order_has_same_hash():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_same_id_changed_payload_visible():
    r = row()
    a = capture({"records": [r]})
    r["native_reference"] = {"grade": "fail", "details": []}
    b = capture({"records": [r]})
    assert compare(a, b)["records"][0]["same_evidence"] is False


def test_missing_left_population_visible():
    r = row()
    a = capture({"records": [r]})
    r2 = copy.deepcopy(r)
    r2["id"] = "second"
    b = capture({"records": [r, r2]})
    assert any(v["left_status"] == "MISSING" for v in compare(a, b)["records"])
