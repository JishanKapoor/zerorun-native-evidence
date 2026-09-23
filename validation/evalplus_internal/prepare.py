"""Seal exposed source bindings and controls before native execution."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evalplus_internal.controls import CONTROLS, NATIVE_PATH, REVISIONS
from evalplus_internal.profiles import parent_profile
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding


def variants(source):
    """Explicit authored source controls; preserve writes and selected anchors.

    These are development stress controls on exposed source, never the 48 R11
    prospectively selected native challenge variants.
    """
    newline = "\r\n" if "\r\n" in source else "\n"
    source = source.replace("\r\n", "\n")
    loop = "            for i, inp in enumerate(inputs):\n"
    normal_commit = "                details[i] = True\n                progress.value += 1\n"
    rejected = "                except BaseException:\n                    details[i] = False\n"
    if source.count(loop) != 1 or source.count(normal_commit) != 1 or source.count(rejected) != 1:
        raise ValueError("Authored development mutation anchor mismatch")
    variants = {
        "pre-decision-skip": source.replace(loop, loop + "                if inp[0] == 999:\n                    continue\n"),
        "accepted-commit-omission": source.replace(normal_commit, "                if i == 0:\n                    continue\n" + normal_commit),
        "rejected-commit-omission": source.replace(rejected, "                except BaseException:\n                    if i == 0:\n                        continue\n                    details[i] = False\n"),
    }
    return {name: text.replace("\n", newline) for name, text in variants.items()}


def prepare(native_sources, output):
    output.mkdir(parents=True, exist_ok=False)
    inventory = []
    sources = {}
    for label, revision in REVISIONS.items():
        sources[label] = (revision, (native_sources / revision / NATIVE_PATH).read_bytes().decode("utf-8"))
    for label, text in variants(sources["after"][1]).items():
        sources[label] = (REVISIONS["after"], text)
    for label, (revision, source) in sources.items():
        folder = output / label
        folder.mkdir()
        profile = parent_profile(source)
        config = (native_sources / revision / "evalplus/config.py").read_bytes().decode("utf-8")
        binding = generate_binding(profile, {NATIVE_PATH: source, "evalplus/config.py": config})
        native_dependencies = {p.relative_to(native_sources / revision).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((native_sources / revision / "evalplus").rglob("*.py"))}
        cases = copy.deepcopy(CONTROLS)
        if label == "pre-decision-skip":
            cases.append({**copy.deepcopy(CONTROLS[0]), "inputs": [[999], [2]], "expected": [999, 2], "id": "legitimate-pre-decision-skip"})
        # Native preflight interruption is a genuine negative for final return.
        negative = {**copy.deepcopy(CONTROLS[0]), "id": "parent-preflight-error", "preflight_error": True}
        payloads = {"profile.json": profile, "binding.json": binding, "controls.json": cases, "parent-negative.json": negative, "native-dependencies.json": native_dependencies}
        (folder / "native.py").write_bytes(source.encode("utf-8"))
        for name, value in payloads.items():
            (folder / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
        inventory.append(dict(id=label, source_revision=revision, native_sha256=hashlib.sha256(source.encode()).hexdigest(), profile_sha256=digest(profile), binding_sha256=binding["sha256"], controls_sha256=digest(cases), authored_source_variant=label not in REVISIONS, control_ids=[case["id"] for case in cases]))
    manifest = dict(schema="evalplus-internal-qualification-design/1", qualified_runtime="Linux CPython 3.11.16/fork/optimize=0", controls=inventory, method="Direct actual worker and separate full native-parent captures are distinct executions; correlate only explicit case/source/input identities", scope="Already exposed source development qualification; no primary historical/challenge count, no independent participant", reference_recipe_sha256=hashlib.sha256(Path(__file__).with_name("reference.py").read_bytes()).hexdigest(), generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    manifest["sha256"] = digest(manifest)
    (output / "design.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.native_sources, arguments.output), indent=2))
