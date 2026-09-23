"""Freeze actual normal-import packages, source bindings and control inventory."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evalplus_internal.controls import CONTROLS, NATIVE_PATH, REVISIONS
from evalplus_internal.prepare import variants as old_variants
from evalplus_path.profiles import profile
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding
from zerorun_harness.lifecycle_binding import generate_lifecycle_binding


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def variants(source):
    result = old_variants(source)
    newline = "\r\n" if "\r\n" in source else "\n"
    text = source.replace("\r\n", "\n")
    normal = "                details[i] = True\n                progress.value += 1\n"
    parent_slice = "    details = details[: progress.value]\n"
    success = "            stat.value = _SUCCESS\n"
    final_return = "    return stat, details\n"
    if any(text.count(anchor) != 1 for anchor in (normal, parent_slice, success, final_return)):
        raise ValueError("Authored development mutation anchor mismatch")
    additions = {
        "wrong-progress": text.replace(normal, "                progress.value += 2\n" + normal),
        "parent-reordered": text.replace(parent_slice, parent_slice + "    details.reverse()\n"),
        "parent-wrong-status": text.replace(final_return, "    if stat == PASS:\n        stat = FAIL\n" + final_return),
        "forced-timeout-state": text.replace(success, success + "            stat.value = _TIMEOUT\n"),
    }
    result.update({name: value.replace("\n", newline) for name, value in additions.items()})
    return result


def prepare(native_sources, output):
    output.mkdir(parents=True, exist_ok=False)
    sources = {
        name: (revision, (native_sources / revision / NATIVE_PATH).read_bytes().decode())
        for name, revision in REVISIONS.items()
    }
    sources.update({
        name: (REVISIONS["after"], text) for name, text in variants(sources["after"][1]).items()
    })
    inventory = []
    for name, (revision, source) in sources.items():
        folder = output / name
        folder.mkdir()
        p = profile(source)
        native_root = native_sources / revision
        config = (native_root / "evalplus/config.py").read_bytes().decode()
        binding = generate_binding(p, {NATIVE_PATH: source, "evalplus/config.py": config})
        lifecycle = generate_lifecycle_binding(binding, {
            NATIVE_PATH: [{"function": "unsafe_execute", "role": "worker"}]})
        for mode in ("original", "observed"):
            root = folder / mode
            root.mkdir()
            for path in sorted((native_root / "evalplus").rglob("*.py")):
                relative = path.relative_to(native_root)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
            (root / NATIVE_PATH).write_bytes((
                source if mode == "original" else lifecycle["transformed"][NATIVE_PATH]
            ).encode())
            hashes = {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*.py"))}
            (folder / (mode + "-files.json")).write_text(json.dumps(hashes, indent=2), encoding="utf-8")
        cases = copy.deepcopy(CONTROLS)
        if name == "pre-decision-skip":
            cases += [
                {**copy.deepcopy(CONTROLS[0]), "id": "skip-only", "inputs": [[999]], "expected": [999]},
                {**copy.deepcopy(CONTROLS[0]), "id": "skip-then-accept", "inputs": [[999], [2]], "expected": [999, 2]},
            ]
        if name == "after":
            cases.append({
                **copy.deepcopy(CONTROLS[0]), "id": "external-parent-timeout",
                "inputs": [[1]], "expected": [1],
                "code": "import signal\ndef check(x):\n    signal.setitimer(signal.ITIMER_REAL, 0)\n    while True: pass",
            })
        cases.append({**copy.deepcopy(CONTROLS[0]), "id": "parent-preflight-error", "preflight_error": True})
        for filename, value in (
            ("profile.json", p), ("binding.json", binding), ("lifecycle.json", lifecycle),
            ("controls.json", cases),
        ):
            (folder / filename).write_text(json.dumps(value, indent=2), encoding="utf-8")
        inventory.append({
            "id": name, "native_revision": revision, "authored_source_variant": name not in REVISIONS,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "profile_sha256": digest(p), "binding_sha256": binding["sha256"],
            "lifecycle_sha256": lifecycle["sha256"], "cases": [case["id"] for case in cases],
            "observed_banks": sum(not c.get("preflight_error") for c in cases),
            "original_reference_banks": sum(not c.get("preflight_error") for c in cases),
        })
    snapshot = output / "implementation"
    shutil.copytree(Path(__file__).resolve().parent, snapshot / "evalplus_path",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The old reusable profile/control builders are retained as declared source
    # dependencies, not copied into the common engine or changed here.
    shutil.copytree(Path(__file__).resolve().parent.parent / "evalplus_internal",
                    snapshot / "evalplus_internal", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    import zerorun_harness
    shutil.copytree(Path(zerorun_harness.__file__).resolve().parent, output / "package/zerorun_harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*")) if p.is_file()}
    design = dict(
        schema="s8-evalplus-one-call-design/1", sources=inventory, files=files,
        native_bank_calls=sum(row["observed_banks"] + row["original_reference_banks"] for row in inventory),
        scope="Exposed authored engineering controls; single bank invocation per original/observed run; no primary historical or participant credit",
        progress_policy="Primary existence/identity only; exact arithmetic independently evaluated in qualification",
        runtime="Linux CPython3.11.16 fork optimize0, original native process target, normal module import",
    )
    design["sha256"] = digest(design)
    (output / "design.json").write_text(json.dumps(design, indent=2), encoding="utf-8")
    return design


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.native_sources, args.output)
    print(json.dumps({"sources": len(result["sources"]), "native_bank_calls": result["native_bank_calls"]}))
