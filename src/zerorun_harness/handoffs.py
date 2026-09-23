# SPDX-License-Identifier: MIT
"""Explicit export levels and finite, source-pinned native component handoffs."""

import copy
import hashlib
from importlib.resources import files
from pathlib import PurePosixPath

from .api import InvalidEvidence, canonical, digest, fingerprint, validate_bundle

MODES = ("native-values", "event-replay", "integration-replay", "native-regression")


def _require(condition, message):
    if not condition:
        raise InvalidEvidence(message)


def _text(value):
    return type(value) is str and 0 < len(value) <= 4096


def native_payload(bundle, recipe):
    """Validate primitives; reference provenance is explicit, not authenticated."""
    validate_bundle(bundle)
    _require(type(recipe) is dict, "A native recipe is required")
    canonical(recipe)
    keys = {
        "schema",
        "record_id",
        "role",
        "maintenance_action",
        "source_files",
        "input",
        "reference_origin_sha256",
        "reference",
        "reference_sha256",
    }
    _require(
        set(recipe) == keys and recipe["schema"] == "zerorun-native-recipe/1",
        "Unsupported native recipe envelope",
    )
    _require(
        recipe["role"] in ("defect-reproducer", "policy-protection"),
        "Invalid regression role",
    )
    _require(_text(recipe["maintenance_action"]), "Maintenance action is required")
    rows = [r for r in bundle["records"] if r["id"] == recipe["record_id"]]
    _require(len(rows) == 1, "Recipe must identify one retained record")
    row = rows[0]
    from .api import profiles

    _require(
        row["provenance"]["source_sha256"]
        in profiles()[row["family"]]["source_sha256"],
        "Unsupported native source profile",
    )
    source = recipe["source_files"]
    _require(
        type(source) is dict and 1 <= len(source) <= 4096, "Invalid source inventory"
    )
    prefix = "evalplus/" if row["family"] == "evalplus" else "swebench/"
    primary = prefix + (
        "eval/__init__.py" if row["family"] == "evalplus" else "harness/grading.py"
    )
    for path, sha in source.items():
        _require(
            type(path) is str
            and path.startswith(prefix)
            and path.endswith(".py")
            and "\\" not in path
            and ":" not in path
            and "\x00" not in path
            and not PurePosixPath(path).is_absolute()
            and all(part not in ("", ".", "..") for part in path.split("/"))
            and fingerprint(sha),
            "Invalid source path or hash",
        )
    _require(
        source.get(primary) == row["provenance"]["source_sha256"],
        "Native source identity mismatch",
    )
    _require(
        fingerprint(recipe["reference_origin_sha256"]),
        "Invalid reference origin identity",
    )
    _require(
        fingerprint(recipe["reference_sha256"])
        and digest(recipe["reference"]) == recipe["reference_sha256"],
        "Native reference digest mismatch",
    )
    inp, ref = recipe["input"], recipe["reference"]
    _require(
        type(inp) is dict and type(ref) is dict,
        "Native input and reference must be objects",
    )
    if row["family"] == "swe":
        _require(
            set(inp) == {"log", "spec"} and type(inp["log"]) is str,
            "Invalid SWE native input",
        )
        _require(
            hashlib.sha256(inp["log"].encode("utf-8")).hexdigest()
            == row["provenance"]["input_sha256"],
            "Native input identity mismatch",
        )
        spec = inp["spec"]
        _require(
            type(spec) is dict
            and set(spec)
            == {
                "instance_id",
                "repo",
                "version",
                "FAIL_TO_PASS",
                "PASS_TO_PASS",
                "log_parser",
            },
            "Invalid native TestSpec",
        )
        _require(
            all(
                _text(spec[k]) for k in ("instance_id", "repo", "version", "log_parser")
            ),
            "Invalid TestSpec text",
        )
        _require(
            all(
                type(spec[k]) is list
                and len(spec[k]) <= 100000
                and all(_text(s) for s in spec[k])
                and len(set(spec[k])) == len(spec[k])
                for k in ("FAIL_TO_PASS", "PASS_TO_PASS")
            ),
            "Invalid native inventory",
        )
        from .api import valid_swe_report

        _require(
            set(ref) == {"selected", "found", "report", "resolution"}
            and type(ref["found"]) is bool
            and type(ref["selected"]) is dict
            and all(
                type(k) is str
                and type(v) is str
                and v in ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL")
                for k, v in ref["selected"].items()
            )
            and valid_swe_report(ref["report"])
            and type(ref["resolution"]) is str
            and ref["resolution"]
            in ("RESOLVED_NO", "RESOLVED_PARTIAL", "RESOLVED_FULL"),
            "Invalid SWE native reference",
        )
    else:
        _require(
            set(inp)
            == {
                "dataset",
                "entry_point",
                "code",
                "inputs",
                "expected",
                "time_limits",
                "atol",
                "fast_check",
            },
            "Invalid native worker arguments",
        )
        _require(
            inp["dataset"] == "humaneval"
            and _text(inp["entry_point"])
            and type(inp["code"]) is str,
            "Unsupported native worker mode",
        )
        _require(
            hashlib.sha256(inp["code"].encode("utf-8")).hexdigest()
            == row["provenance"]["candidate_sha256"],
            "Native candidate identity mismatch",
        )
        _require(
            digest(inp["inputs"]) == row["provenance"]["input_sha256"],
            "Native input identity mismatch",
        )
        _require(
            type(inp["inputs"]) is list
            and 1 <= len(inp["inputs"]) <= 100000
            and all(type(v) is list for v in inp["inputs"]),
            "Invalid native input bank",
        )
        n = len(inp["inputs"])
        _require(
            type(inp["expected"]) is list
            and len(inp["expected"]) == n
            and type(inp["time_limits"]) is list
            and len(inp["time_limits"]) == n
            and all(type(v) in (int, float) and 0 < v <= 10 for v in inp["time_limits"])
            and sum(inp["time_limits"]) <= 60
            and type(inp["atol"]) in (int, float)
            and inp["atol"] >= 0
            and type(inp["fast_check"]) is bool,
            "Invalid native worker limits or values",
        )
        _require(
            set(ref) == {"worker_status", "progress", "details"}
            and type(ref["worker_status"]) is int
            and ref["worker_status"] in (0, 1)
            and type(ref["progress"]) is int
            and 0 <= ref["progress"] <= n
            and type(ref["details"]) is list
            and len(ref["details"]) == n
            and all(type(v) is bool for v in ref["details"]),
            "Invalid native worker reference",
        )
    payload = {
        "schema": "zerorun-native-handoff/1",
        "family": row["family"],
        "level": "native-component-regression",
        "capture_sha256": bundle["sha256"],
        "record_sha256": digest(row),
        "provenance": copy.deepcopy(row["provenance"]),
        "recipe": copy.deepcopy(recipe),
    }
    # Qualification labels are deliberately absent; assertions consume native values.
    return payload


def export_level(bundle, mode, recipe=None):
    validate_bundle(bundle)
    _require(type(mode) is str and mode in MODES, "Unsupported export mode")
    if mode != "native-regression":
        _require(recipe is None, "Recipes are only accepted for native regressions")
    if mode == "event-replay":
        return copy.deepcopy(bundle)
    if mode == "integration-replay":
        data = canonical(bundle).decode("utf-8")
        return (
            "# Workbench-dependent integration replay; not a native regression.\n"
            "import json\nfrom zerorun_harness import audit\n"
            f"bundle = json.loads({data!r})\n"
            "print(json.dumps(audit(bundle),sort_keys=True,allow_nan=False))\n"
        )
    if mode == "native-regression":
        payload = native_payload(bundle, recipe)
        template = (
            files("zerorun_harness")
            .joinpath("resources/native_runner.py.txt")
            .read_text(encoding="utf-8")
        )
        _require(
            template.count("__PAYLOAD_LITERAL__") == 1,
            "Invalid installed native template",
        )
        payload["template_sha256"] = hashlib.sha256(
            template.encode("utf-8")
        ).hexdigest()
        return template.replace(
            "__PAYLOAD_LITERAL__", repr(canonical(payload).decode("utf-8"))
        )
    raise InvalidEvidence("Use the default native-values export through export()")
