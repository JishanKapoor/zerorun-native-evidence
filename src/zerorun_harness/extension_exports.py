# SPDX-License-Identifier: MIT
"""Finite native API handoffs; generated programs never import ZeroRun."""

import copy
from importlib.resources import files
import re

from .api import canonical, digest, fingerprint
from .binding import safe_path
from .declarative import data_boundary, exact, require, text


@data_boundary
def native_script(bundle, recipe):
    from .extensions import audit

    audit(bundle)
    exact(
        recipe,
        [
            "schema",
            "source_files",
            "module",
            "function",
            "args",
            "kwargs",
            "reference_origin_sha256",
            "justification",
        ],
        "extension native recipe",
    )
    require(recipe["schema"] in {
        "zerorun-extension-native-recipe/1", "zerorun-extension-native-recipe/2"
    }, "Unsupported native recipe")
    needs_v2 = any(set(rule) & {"guard", "inventory_policy"}
                   for rule in bundle["policy"]["rules"]) or any(
                       set(site) & {"batch", "producer_role"}
                       for site in bundle["policy"]["sites"].values())
    version_two = recipe["schema"] == "zerorun-extension-native-recipe/2"
    require(not needs_v2 or version_two,
            "Native guards, batches and scoped completion require recipe version 2")
    require(
        type(recipe["source_files"]) is dict
        and 1 <= len(recipe["source_files"]) <= 4096,
        "Invalid native source inventory",
    )
    require(
        all(safe_path(k) and fingerprint(v) for k, v in recipe["source_files"].items()),
        "Invalid native source identity",
    )
    require(
        all(
            recipe["source_files"].get(k) == v
            for k, v in bundle["binding"]["original_sources"].items()
        ),
        "Native export must retain original source identity",
    )
    require(
        type(recipe["module"]) is str
        and re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", recipe["module"])
        is not None,
        "Invalid native module",
    )
    require(
        recipe["module"].replace(".", "/") + ".py" in recipe["source_files"],
        "Native module source not pinned",
    )
    require(
        type(recipe["function"]) is str
        and recipe["function"].isidentifier()
        and not recipe["function"].startswith("_"),
        "Invalid native entry point",
    )
    require(
        type(recipe["args"]) is list
        and len(recipe["args"]) <= 16
        and type(recipe["kwargs"]) is dict
        and len(recipe["kwargs"]) <= 32,
        "Invalid native call inputs",
    )
    require(
        all(type(k) is str and k.isidentifier() for k in recipe["kwargs"]),
        "Invalid native argument names",
    )
    require(
        fingerprint(recipe["reference_origin_sha256"])
        and text(recipe["justification"]),
        "Native assertion qualification provenance required",
    )
    canonical(recipe)
    payload = dict(
        schema="zerorun-standalone-relationships/1",
        export_version="1.0.0",
        policy=copy.deepcopy(bundle["policy"]),
        recipe=copy.deepcopy(recipe),
        case_sha256=digest(bundle["case"]),
        binding_sha256=bundle["binding"]["sha256"],
        qualification_sha256=bundle["qualification"]["sha256"],
    )
    if version_two:
        payload.update(
            schema="zerorun-standalone-relationships/2",
            export_version="2.0.0",
            expected_inventory=copy.deepcopy(bundle["case"]["inventory"]),
            native_result_schema="inventory/facts/native_complete/native_batches-v2",
        )
    # No classifier/status/report is copied into the native assertion program.
    template = (
        files("zerorun_harness")
        .joinpath("resources/extension_native_template_v2.txt" if version_two
                  else "resources/extension_native_template.txt")
        .read_text(encoding="utf-8")
    )
    return template.replace(
        "__PAYLOAD_JSON__", repr(canonical(payload).decode("utf-8"))
    ).replace("__PAYLOAD_SHA__", digest(payload))
