# SPDX-License-Identifier: MIT
"""Canonical bundles and typed evidence operations.

Hashes identify bytes, not authorship or truth. Callers supply native observations
from an accountable acquisition process; this module never runs candidate code.
"""

import copy, hashlib, json
from collections import Counter
from importlib.resources import files
from . import checks

SCHEMA = "zerorun-capture/1"
MAX_RECORDS = 4096
HEX = set("0123456789abcdef")


class InvalidEvidence(ValueError):
    pass


def canonical(value):
    active = set()

    def validate(node, depth=0):
        if depth > 64:
            raise InvalidEvidence("JSON nesting exceeds 64 levels")
        kind = type(node)
        if node is None or kind in (str, int, float, bool):
            return
        if kind not in (dict, list):
            raise InvalidEvidence("Only exact JSON types are accepted")
        ident = id(node)
        if ident in active:
            raise InvalidEvidence("Cyclic data is not JSON")
        active.add(ident)
        if kind is dict:
            if any(type(k) is not str for k in node):
                raise InvalidEvidence("JSON object keys must be strings")
            for item in node.values():
                validate(item, depth + 1)
        else:
            for item in node:
                validate(item, depth + 1)
        active.remove(ident)

    validate(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidEvidence("Evidence must be finite JSON data") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def fingerprint(value):
    return type(value) is str and len(value) == 64 and set(value) <= HEX


def profiles():
    return json.loads(
        files("zerorun_harness")
        .joinpath("resources/profiles.json")
        .read_text(encoding="utf-8")
    )


def validate_records(records):
    if type(records) is not list or not 1 <= len(records) <= MAX_RECORDS:
        raise InvalidEvidence("Expected 1..4096 records")
    ids = set()
    for row in records:
        if type(row) is not dict or set(row) != set(
            ["id", "family", "provenance", "observation", "native_reference"]
        ):
            raise InvalidEvidence("Invalid record keys")
        ident = row["id"]
        if type(ident) is not str or not ident or len(ident) > 1024 or ident in ids:
            raise InvalidEvidence("Invalid or duplicate record identity")
        ids.add(ident)
        if type(row["family"]) is not str or row["family"] not in ("evalplus", "swe"):
            raise InvalidEvidence("Unknown family")
        prov = row["provenance"]
        if type(prov) is not dict or set(prov) != set(
            ["source_sha256", "input_sha256", "candidate_sha256"]
        ):
            raise InvalidEvidence("Invalid provenance fields")
        if any(not fingerprint(v) for v in prov.values()):
            raise InvalidEvidence("Invalid SHA256 identity")
        if type(row["observation"]) is not dict:
            raise InvalidEvidence("Observation must be a JSON object")
        if (
            row["native_reference"] is not None
            and type(row["native_reference"]) is not dict
        ):
            raise InvalidEvidence("Native reference must be an object or null")
    canonical(records)


def capture(manifest):
    """Import existing native records into a content-identified bundle."""
    if type(manifest) is not dict or set(manifest) != set(["records"]):
        raise InvalidEvidence("Manifest requires only records")
    validate_records(manifest["records"])
    records = copy.deepcopy(manifest["records"])
    payload = {"schema": SCHEMA, "mode": "saved-evidence", "records": records}
    return {**payload, "sha256": digest(payload)}


def validate_bundle(bundle):
    if type(bundle) is not dict or set(bundle) != set(
        ["schema", "mode", "records", "sha256"]
    ):
        raise InvalidEvidence("Invalid capture envelope")
    if bundle["schema"] != SCHEMA or bundle["mode"] != "saved-evidence":
        raise InvalidEvidence("Unsupported capture schema or mode")
    payload = {k: v for k, v in bundle.items() if k != "sha256"}
    if not fingerprint(bundle["sha256"]) or digest(payload) != bundle["sha256"]:
        raise InvalidEvidence("Capture digest mismatch")
    validate_records(bundle["records"])


def native_agreement_fields(row):
    """Declared fields in the comparison; null agreement means unassessable."""
    ref = row["native_reference"]
    if ref is None:
        return []
    if row["family"] == "evalplus":
        return ["grade", "details"]
    return ["selected"] + [k for k in ("found", "report", "resolution") if k in ref]


def valid_swe_report(value):
    categories = {"FAIL_TO_PASS", "PASS_TO_PASS", "FAIL_TO_FAIL", "PASS_TO_FAIL"}
    if type(value) is not dict or set(value) != categories:
        return False
    for outcomes in value.values():
        if type(outcomes) is not dict or set(outcomes) != {"success", "failure"}:
            return False
        for identities in outcomes.values():
            if type(identities) is not list or any(
                type(i) is not str for i in identities
            ):
                return False
    return True


def native_agreement(row):
    """Diagnostic comparison to separately acquired native values, never an oracle label."""
    ref = row["native_reference"]
    obs = row["observation"]
    if ref is None:
        return None
    if row["family"] == "swe":
        selections = [ref.get("selected"), obs.get("selected")]
        if not all(
            type(v) is dict
            and all(
                type(k) is str
                and type(s) is str
                and s in ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL")
                for k, s in v.items()
            )
            for v in selections
        ):
            return None
        matches = [selections[0] == selections[1]]
        for key, observed in [
            ("found", "found"),
            ("report", "native_report"),
            ("resolution", "native_resolution"),
        ]:
            if key not in ref:
                continue
            a, b = ref[key], obs.get(observed)
            if key == "found" and (type(a) is not bool or type(b) is not bool):
                return None
            if key == "report" and (not valid_swe_report(a) or not valid_swe_report(b)):
                return None
            if key == "resolution" and any(
                type(v) is not str
                or v not in ("RESOLVED_NO", "RESOLVED_PARTIAL", "RESOLVED_FULL")
                for v in [a, b]
            ):
                return None
            matches.append(a == b)
        return all(matches)
    state = obs.get("state")
    grade = ref.get("grade")
    details = ref.get("details")
    if (
        type(state) is not dict
        or grade not in ("pass", "fail", "timeout")
        or type(details) is not list
        or any(type(v) is not bool for v in details)
    ):
        return None
    if (
        type(state.get("details")) is not list
        or any(type(v) is not bool for v in state["details"])
        or type(state.get("progress")) is not int
    ):
        return None
    p = state["progress"]
    cells = state["details"]
    status = state.get("worker_status")
    if status not in (0, 1) or type(status) is not int or not 0 <= p <= len(cells):
        return None
    health = obs.get("health")
    if type(health) is not dict or health.get("native_complete") is not True:
        return None
    inferred = "pass" if status == 0 and p == len(cells) and all(cells) else "fail"
    return inferred == grade and cells[:p] == details


def audit(bundle):
    """Check the finite grammar. Native reference agreement is reported separately."""
    validate_bundle(bundle)
    policy = profiles()
    rows = []
    for r in bundle["records"]:
        provenance = r["provenance"]
        obs = r["observation"]
        supported = (
            provenance["source_sha256"] in policy[r["family"]]["source_sha256"]
            and obs.get("source_sha256") == provenance["source_sha256"]
        )
        relationship = getattr(checks, r["family"])(obs) if supported else "UNSUPPORTED"
        agreement = native_agreement(r) if supported else None
        unavailable = r["native_reference"] is not None and agreement is None
        status = (
            "INCONCLUSIVE"
            if relationship in ("CONFORMS", "VIOLATION")
            and (agreement is False or unavailable)
            else relationship
        )
        reasons = []
        if agreement is False:
            reasons.append("independent_native_values_disagree")
        if unavailable and supported:
            reasons.append("independent_native_reference_unassessable")
        if relationship == "INCONCLUSIVE":
            reasons.append("incomplete_observation_or_native_premises")
        if relationship == "UNSUPPORTED":
            reasons.append("unsupported_source_or_grammar")
        rows.append(
            {
                "id": r["id"],
                "family": r["family"],
                "status": status,
                "relationship_status": relationship,
                "native_agreement": agreement,
                "native_agreement_fields": native_agreement_fields(r)
                if supported
                else [],
                "reasons": reasons,
                "evidence_sha256": digest(r),
                "source_sha256": provenance["source_sha256"],
            }
        )
    body = {
        "schema": "zerorun-audit/2",
        "capture_sha256": bundle["sha256"],
        "profile_sha256": digest(policy),
        "records": rows,
        "counts": dict(sorted(Counter(r["status"] for r in rows).items())),
    }
    return {**body, "sha256": digest(body)}


def compare(left, right):
    """Compare whole inventories by identity; preserve missing records and changed evidence."""
    a = audit(left)
    b = audit(right)
    aa = {r["id"]: r for r in a["records"]}
    bb = {r["id"]: r for r in b["records"]}
    rows = []
    left_records = {r["id"]: r for r in left["records"]}
    right_records = {r["id"]: r for r in right["records"]}
    for ident in sorted(aa.keys() | bb.keys()):
        l = aa.get(ident)
        r = bb.get(ident)
        mismatches = []
        if l and r:
            x, y = left_records[ident], right_records[ident]
            if x["family"] != y["family"]:
                mismatches.append("family")
            for key in ["input_sha256", "candidate_sha256"]:
                if x["provenance"][key] != y["provenance"][key]:
                    mismatches.append(key)
        alignment = (
            "MISSING" if not (l and r) else "MISMATCH" if mismatches else "MATCHED"
        )
        rows.append(
            {
                "id": ident,
                "left_status": l["status"] if l else "MISSING",
                "right_status": r["status"] if r else "MISSING",
                "same_evidence": bool(
                    l and r and l["evidence_sha256"] == r["evidence_sha256"]
                ),
                "identity_alignment": alignment,
                "identity_mismatches": mismatches,
            }
        )
    return {
        "schema": "zerorun-compare/2",
        "left_sha256": left["sha256"],
        "right_sha256": right["sha256"],
        "records": rows,
    }


def export(bundle):
    """Export primitive native fields with qualification, never convert a verdict into a score."""
    result = audit(bundle)
    byid = {r["id"]: r for r in result["records"]}
    rows = []
    for r in bundle["records"]:
        state = copy.deepcopy(
            r["observation"].get("state")
            if r["family"] == "evalplus"
            else r["observation"].get("selected")
        )
        native_fields = (
            copy.deepcopy(r["observation"].get("state"))
            if r["family"] == "evalplus"
            else {
                key: copy.deepcopy(r["observation"][field])
                for key, field in [
                    ("selected", "selected"),
                    ("found", "found"),
                    ("report", "native_report"),
                    ("resolution", "native_resolution"),
                ]
                if field in r["observation"]
            }
        )
        rows.append(
            {
                "id": r["id"],
                "family": r["family"],
                "provenance": copy.deepcopy(r["provenance"]),
                "native_state": state,
                "native_fields": native_fields,
                "independent_native_reference": copy.deepcopy(r["native_reference"]),
                "qualification": byid[r["id"]]["status"],
                "native_agreement": byid[r["id"]]["native_agreement"],
                "native_agreement_fields": byid[r["id"]]["native_agreement_fields"],
            }
        )
    return {
        "schema": "zerorun-native-export/2",
        "capture_sha256": bundle["sha256"],
        "records": rows,
    }


def report(bundle):
    """Deterministic readable report over retained facts; no native recalculation."""
    result = audit(bundle)
    lines = [
        "ZeroRun saved-evidence report",
        "Capture SHA256: " + bundle["sha256"],
        "Records: " + str(len(result["records"])),
        "",
        "Qualification counts:",
    ]
    lines += [k + ": " + str(v) for k, v in sorted(result["counts"].items())]
    lines += ["", "Record\tFamily\tQualification\tNative agreement"]
    for r in result["records"]:
        lines.append(
            json.dumps(r["id"], ensure_ascii=True)
            + "\t"
            + r["family"]
            + "\t"
            + r["status"]
            + "\t"
            + json.dumps(r["native_agreement"])
        )
    lines += [
        "",
        "Scope: pinned saved observations; integrity hashes are not authenticity proofs.",
        "Conformance is not candidate correctness or evidence of independent adoption.",
    ]
    return "\n".join(lines) + "\n"
