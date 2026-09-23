"""Source-pinned native loading and authored log construction, without semantics.

No grading decision is calculated in this driver. The original native report is
returned unchanged. The same driver accepts the mechanical transformed files.
"""
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import types


def source_inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "swebench").rglob("*.py"))}


def load_native(root, source_hashes, transformed=None, observe=None):
    root = Path(root)
    for relative, expected in source_hashes.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Native source digest mismatch: " + relative)
    for name in list(sys.modules):
        if name == "swebench" or name.startswith("swebench."):
            del sys.modules[name]

    class Loader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if not fullname.startswith("swebench."):
                return None
            module_path = fullname.replace(".", "/") + ".py"
            package_path = fullname.replace(".", "/") + "/__init__.py"
            relative = module_path if (root / module_path).is_file() else package_path
            if relative not in source_hashes:
                return None
            spec = importlib.util.spec_from_loader(fullname, self, is_package=relative == package_path)
            spec.loader_state = relative
            spec.origin = str(root / relative)
            return spec

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            relative = module.__spec__.loader_state
            module.__file__ = str(root / relative)
            if module.__spec__.submodule_search_locations is not None:
                module.__path__ = [str((root / relative).parent)]
            original = (root / relative).read_bytes()
            if hashlib.sha256(original).hexdigest() != source_hashes[relative]:
                raise ValueError("Native source changed during import")
            source = transformed.get(relative, original) if transformed else original
            if observe is not None:
                module.__dict__["__zr_observe"] = observe
            exec(compile(source, str(root / relative), "exec"), module.__dict__)

    for name, relative in [("swebench", "swebench"), ("swebench.harness", "swebench/harness")]:
        namespace = types.ModuleType(name)
        namespace.__path__ = [str(root / relative)]
        sys.modules[name] = namespace
    loader = Loader()
    sys.meta_path.insert(0, loader)
    try:
        module = importlib.import_module("swebench.harness.grading")
    finally:
        sys.meta_path.remove(loader)
    return module


def invoke(native, case, work):
    """Call the actual native pipeline once; do not infer any expected outcome."""
    if case["id"] == "no-native-call":
        return None
    f2p = "tests/test_control.py::test_repair"
    p2p = "tests/test_control.py::test_maintenance"
    rows = [status + " " + name for name, status in zip([f2p, p2p], case["statuses"]) if status]
    repair_tests = [f2p]
    if "second_repair" in case:
        name = "tests/test_control.py::test_second_repair"
        repair_tests.append(name)
        rows.append(case["second_repair"] + " " + name)
    if case.get("extra"):
        rows.append(case["extra"])
    body = "\n".join(rows) + "\n"
    start, end = ">>>>> Start Test Output\n", ">>>>> End Test Output\n"
    if case["layout"] == "outside":
        content = body + start + "ordinary runner text\n" + end
    elif case["layout"] == "missing":
        content = body
    else:
        content = start + body + end
        if case["layout"] == "bad":
            content += ">>>>> Tests Timed Out\n"
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    log = work / "native.log"
    log.write_bytes(content.encode())
    spec = types.SimpleNamespace(log_parser="parse_log_pytest", instance_id="authored-control",
        FAIL_TO_PASS=repair_tests, PASS_TO_PASS=[p2p], eval_type="pass_and_fail")
    prediction = {"instance_id": "authored-control", "model_patch": None if case.get("patch_is_none") else "authored nonempty development control"}
    report = native.get_eval_report(spec, prediction, str(log), include_tests_status=True)
    # This is an explicitly authored artifact boundary using Python's ordinary
    # serializer. It is not presented as observing run_evaluation's Docker path.
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    (work / "native-report.json").write_bytes(encoded.encode())
    assert json.loads(encoded) == report
    return report
