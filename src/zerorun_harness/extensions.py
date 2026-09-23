# SPDX-License-Identifier: MIT
"""Installed declarative resources discovered without executing entry points."""

import copy
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re

from .api import InvalidEvidence, canonical, digest, fingerprint
from .binding import validate_binding
from .declarative import (
    data_boundary,
    evaluate,
    exact,
    require,
    seal,
    text,
    unseal,
    validate_profile,
)
from .qualification import validate_qualification

GROUP = "zerorun.extensions.v1"
MANIFEST = "zerorun-extension-manifest/1"
BUNDLE = "zerorun-extension-capture/1"


@data_boundary
def load_extension(selection):
    exact(selection, ["id", "version", "sha256"], "extension selection")
    require(
        text(selection["id"])
        and text(selection["version"])
        and fingerprint(selection["sha256"]),
        "Invalid extension identity",
    )
    candidates = []
    registrations = set()
    for dist in metadata.distributions():
        for entry in dist.entry_points:
            if entry.group == GROUP and entry.name == selection["id"]:
                # importlib.metadata may enumerate the same installation twice
                # when sys.path repeats a directory. Resolve physical origins;
                # distinct distributions/resources remain genuinely ambiguous.
                identity = (
                    str(Path(dist.locate_file("")).resolve()),
                    dist.metadata.get("Name"),
                    dist.version,
                    entry.value,
                )
                if identity in registrations:
                    continue
                registrations.add(identity)
                candidates.append((dist, entry))
    require(
        len(candidates) == 1,
        "Extension must resolve to exactly one installed distribution",
    )
    dist, entry = candidates[0]
    # entry.load() is deliberately prohibited: registration supplies a packaged
    # JSON resource, never an executable checker factory or import side effect.
    match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z0-9_./-]+\.json)", entry.value
    )
    require(match is not None, "Entry point must name a declarative JSON resource")
    package, resource = match.groups()
    path = package.replace(".", "/") + "/" + resource
    require(
        all(part not in ("", ".", "..") for part in PurePosixPath(path).parts),
        "Unsafe extension resource path",
    )
    inventory = {str(p).replace("\\", "/") for p in dist.files or []}
    require(
        path in inventory and dist.version == selection["version"],
        "Extension distribution/resource identity mismatch",
    )
    origin = dist.locate_file(path)
    require(origin.stat().st_size <= 1024 * 1024, "Extension profile exceeds 1 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate extension JSON key")
            result[key] = value
        return result

    try:
        profile = json.loads(
            origin.read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except (ValueError, UnicodeError) as exc:
        raise InvalidEvidence("Invalid installed declaration JSON") from exc
    validate_profile(profile)
    require(
        profile["id"] == selection["id"]
        and profile["version"] == selection["version"]
        and digest(profile) == selection["sha256"],
        "Installed profile identity mismatch",
    )
    return profile


@data_boundary
def capture(manifest):
    exact(
        manifest,
        [
            "schema",
            "extension",
            "binding",
            "case",
            "observations",
            "health",
            "qualification",
        ],
        "extension manifest",
    )
    require(manifest["schema"] == MANIFEST, "Unsupported extension manifest")
    p = load_extension(manifest["extension"])
    validate_binding(p, manifest["binding"])
    q = validate_qualification(p, manifest["binding"], manifest["qualification"])
    require(
        manifest["health"]["sites"] == q["sites"]
        and manifest["health"]["qualification_sha256"]
        == manifest["qualification"]["sha256"],
        "Health must use retained qualification evidence",
    )
    require(
        manifest["case"]["source_sha256"]
        == digest(manifest["binding"]["original_sources"]),
        "Case source identity does not match binding",
    )
    evaluate(
        p,
        manifest["case"],
        manifest["observations"],
        manifest["health"],
        manifest["binding"]["sha256"],
    )
    return seal(
        dict(
            schema=BUNDLE,
            mode="saved-qualified-relationships",
            extension=copy.deepcopy(manifest["extension"]),
            policy=copy.deepcopy(p),
            binding=copy.deepcopy(manifest["binding"]),
            case=copy.deepcopy(manifest["case"]),
            observations=copy.deepcopy(manifest["observations"]),
            health=copy.deepcopy(manifest["health"]),
            qualification=copy.deepcopy(manifest["qualification"]),
            components={
                "engine": "1.0.0",
                "policy": {"id": p["id"], "version": p["version"], "sha256": digest(p)},
                "binding": {
                    "version": manifest["binding"]["grammar_version"],
                    "sha256": manifest["binding"]["sha256"],
                },
                "export": {"version": "1.0.0"},
                "case": {
                    "version": manifest["case"]["version"],
                    "sha256": digest(manifest["case"]),
                },
            },
        )
    )


@data_boundary
def audit(bundle):
    b = unseal(bundle, BUNDLE)
    exact(
        b,
        [
            "schema",
            "mode",
            "extension",
            "policy",
            "binding",
            "case",
            "observations",
            "health",
            "qualification",
            "components",
        ],
        "archived extension capture",
    )
    require(
        b["mode"] == "saved-qualified-relationships",
        "Unsupported archived extension mode",
    )
    # Archived interpretation is bound to its embedded declarations. Installed
    # package updates may not silently retarget previously captured observations.
    p = validate_profile(b["policy"])
    exact(b["extension"], ["id", "version", "sha256"], "archived extension selection")
    require(
        b["extension"]["id"] == p["id"]
        and b["extension"]["version"] == p["version"]
        and digest(p) == b["extension"]["sha256"],
        "Archived extension identity mismatch",
    )
    validate_binding(p, b["binding"])
    q = validate_qualification(p, b["binding"], b["qualification"])
    require(
        b["health"]["sites"] == q["sites"]
        and b["health"]["qualification_sha256"] == b["qualification"]["sha256"],
        "Archived health/qualification mismatch",
    )
    require(
        b["case"]["source_sha256"] == digest(b["binding"]["original_sources"]),
        "Archived source identity mismatch",
    )
    require(
        b["components"]
        == {
            "engine": "1.0.0",
            "policy": {"id": p["id"], "version": p["version"], "sha256": digest(p)},
            "binding": {
                "version": b["binding"]["grammar_version"],
                "sha256": b["binding"]["sha256"],
            },
            "export": {"version": "1.0.0"},
            "case": {"version": b["case"]["version"], "sha256": digest(b["case"])},
        },
        "Component identity mismatch",
    )
    return evaluate(
        p, b["case"], b["observations"], b["health"], b["binding"]["sha256"]
    )


def compare(left, right):
    aa, bb = audit(left), audit(right)
    a = {(r["relationship"], canonical(r["identity"])): r for r in aa["records"]}
    b = {(r["relationship"], canonical(r["identity"])): r for r in bb["records"]}
    rows = []
    for ident in sorted(a.keys() | b.keys()):
        l, r = a.get(ident), b.get(ident)
        rows.append(
            dict(
                relationship=ident[0],
                identity=json.loads(ident[1]),
                left=l["status"] if l else "MISSING",
                right=r["status"] if r else "MISSING",
                same_policy=left["extension"] == right["extension"],
                same_native_input=left["case"]["input_sha256"]
                == right["case"]["input_sha256"],
            )
        )
    return seal(
        dict(
            schema="zerorun-extension-compare/1",
            left_sha256=left["sha256"],
            right_sha256=right["sha256"],
            records=rows,
        )
    )


def export(bundle, *, mode="native-values", recipe=None):
    result = audit(bundle)
    if mode == "native-regression":
        from .extension_exports import native_script

        return native_script(bundle, recipe)
    require(
        recipe is None,
        "Extension native recipes use the declared native export interface",
    )
    require(
        mode in ["native-values", "event-replay", "integration-replay"],
        "Unsupported extension export level",
    )
    if mode == "native-values":
        return seal(
            dict(
                schema="zerorun-extension-values/1",
                capture_sha256=bundle["sha256"],
                native_observations=copy.deepcopy(bundle["observations"]),
                qualification=result,
            )
        )
    if mode == "event-replay":
        return seal(
            dict(
                schema="zerorun-extension-event-replay/1",
                level=mode,
                framework_required=True,
                policy=copy.deepcopy(bundle["policy"]),
                case=copy.deepcopy(bundle["case"]),
                events=copy.deepcopy(bundle["observations"]),
                health=copy.deepcopy(bundle["health"]),
                binding_sha256=bundle["binding"]["sha256"],
                expected_interpretation_sha256=result["sha256"],
            )
        )
    return seal(
        dict(
            schema="zerorun-extension-replay/1",
            level=mode,
            framework_required=True,
            capture=copy.deepcopy(bundle),
            expected_interpretation_sha256=result["sha256"],
        )
    )


def report(bundle):
    a = audit(bundle)
    lines = [
        "ZeroRun native-relationship report",
        "Capture SHA256: " + bundle["sha256"],
        "Policy SHA256: " + a["policy_sha256"],
        "Binding SHA256: " + a["binding_sha256"],
        "",
    ]
    for row in a["records"]:
        lines.append(json.dumps(row, sort_keys=True, ensure_ascii=True))
    lines.append(
        "Qualified native relationships only; no candidate correctness or independent adoption claim."
    )
    return "\n".join(lines) + "\n"
