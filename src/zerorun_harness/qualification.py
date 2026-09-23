# SPDX-License-Identifier: MIT
"""Conditional site qualification from retained native control references.

Reference provenance is inspectable evidence, not cryptographic authentication of
scientific independence. No primary expected grade enters relationship checking.
"""

import copy

from .api import canonical, digest, fingerprint
from .binding import validate_binding
from .declarative import (
    data_boundary,
    exact,
    require,
    seal,
    text,
    unseal,
    validate_profile,
)


@data_boundary
def qualify(profile, binding, controls):
    p = validate_profile(profile)
    validate_binding(p, binding)
    canonical(controls)
    require(
        type(controls) is list and 1 <= len(controls) <= 1024,
        "Invalid qualification control inventory",
    )
    by_site = {site: [] for site in p["sites"]}
    ids = set()
    rows = []
    for control in controls:
        exact(
            control,
            ["id", "site", "role", "reference", "observed"],
            "qualification control",
        )
        require(
            text(control["id"]) and control["id"] not in ids,
            "Duplicate/invalid qualification control",
        )
        ids.add(control["id"])
        require(
            type(control["site"]) is str
            and control["site"] in by_site
            and control["role"] in ["positive", "negative"],
            "Unsupported qualification control",
        )
        ref = control["reference"]
        exact(
            ref,
            [
                "source_sha256",
                "recipe_sha256",
                "output_sha256",
                "native_source_sha256",
                "framework_semantics_imported",
                "facts",
            ],
            "native control reference",
        )
        require(
            all(
                fingerprint(ref[k])
                for k in [
                    "source_sha256",
                    "recipe_sha256",
                    "output_sha256",
                    "native_source_sha256",
                ]
            ),
            "Invalid native reference provenance",
        )
        require(
            ref["framework_semantics_imported"] is False,
            "Reference must not use production framework semantics",
        )
        require(
            ref["native_source_sha256"] == digest(binding["original_sources"]),
            "Qualification native source mismatch",
        )
        require(
            type(ref["facts"]) is list
            and len(ref["facts"]) <= 4096
            and digest(ref["facts"]) == ref["output_sha256"],
            "Native reference output mismatch",
        )
        require(
            type(control["observed"]) is list and len(control["observed"]) <= 4096,
            "Invalid observed controls",
        )
        if control["role"] == "positive":
            require(bool(ref["facts"]), "Positive control requires native witness")
        else:
            require(
                ref["facts"] == [],
                "Negative control must independently establish no applicable observation",
            )
        expected, observed = [], []
        for fact in ref["facts"]:
            exact(fact, ["identity", "values"], "reference fact")
            expected.append(copy.deepcopy(fact))
        for event in control["observed"]:
            require(
                type(event) is dict
                and event.get("site") == control["site"]
                and event.get("binding_sha256") == binding["sha256"],
                "Observed control binding/site mismatch",
            )
            observed.append(
                dict(identity=event.get("identity"), values=event.get("values"))
            )
        # Match complete typed native identity/value inventories, not only labels
        # or a production observer's claimed health flag.
        passed = sorted(canonical(v) for v in expected) == sorted(
            canonical(v) for v in observed
        )
        row = dict(
            id=control["id"],
            site=control["site"],
            role=control["role"],
            passed=passed,
            reference_sha256=digest(ref),
            observation_sha256=digest(control["observed"]),
        )
        rows.append(row)
        by_site[control["site"]].append(row)
    sites = {}
    for site, evidence in by_site.items():
        required_roles = (
            {"positive"}
            if p["sites"][site]["position"] == "after"
            else {"positive", "negative"}
        )
        sites[site] = (
            bool(evidence)
            and required_roles <= {row["role"] for row in evidence}
            and all(row["passed"] for row in evidence)
        )
    return seal(
        dict(
            schema="zerorun-site-qualification/1",
            policy_sha256=digest(p),
            binding_sha256=binding["sha256"],
            runtime=copy.deepcopy(binding["runtime"]),
            sites=sites,
            controls=copy.deepcopy(controls),
            checks=rows,
            scope="Conditional on disclosed native reference provenance and qualified runtime; not arbitrary-source or independent-user certification",
        )
    )


def validate_qualification(profile, binding, certificate):
    q = unseal(certificate, "zerorun-site-qualification/1")
    regenerated = qualify(profile, binding, q.get("controls"))
    require(
        regenerated == certificate,
        "Qualification certificate does not follow retained native controls",
    )
    return q
