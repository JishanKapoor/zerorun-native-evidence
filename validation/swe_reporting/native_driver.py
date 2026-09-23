"""Original SWE module imports and native saved-log operations, without policy.

Every SWE module, including package initializers, executes its actual source.
The integrity loader only verifies bytes and substitutes generated bound files.
No native dependency, class, grading function or serializer is stubbed.
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys


def source_inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "swebench").rglob("*.py"))}


def load_native(root, hashes, transformed=None, observe=None):
    root = Path(root).resolve()
    if source_inventory(root) != hashes:
        raise ValueError("Native source inventory changed")
    for name in list(sys.modules):
        if name == "swebench" or name.startswith("swebench."):
            del sys.modules[name]

    class VerifiedLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            relative = Path(self.path).relative_to(root).as_posix()
            original = Path(self.path).read_bytes()
            if hashlib.sha256(original).hexdigest() != hashes[relative]:
                raise ValueError("Native source changed while importing")
            source = (transformed or {}).get(relative, original)
            return compile(source, self.path, "exec")

        def exec_module(self, module):
            if observe is not None and Path(self.path).relative_to(root).as_posix() in (transformed or {}):
                module.__dict__["__zr_observe"] = observe
            super().exec_module(module)

    class VerifiedFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "swebench" and not fullname.startswith("swebench."):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or not spec.origin:
                raise ImportError("Unresolved native module: " + fullname)
            relative = Path(spec.origin).resolve().relative_to(root).as_posix()
            if relative not in hashes:
                raise ImportError("Unpinned native module: " + fullname)
            spec.loader = VerifiedLoader(fullname, spec.origin)
            return spec

    finder = VerifiedFinder()
    sys.path.insert(0, str(root))
    sys.meta_path.insert(0, finder)
    try:
        evaluation = importlib.import_module("swebench.harness.run_evaluation")
        reporting = importlib.import_module("swebench.harness.reporting")
        types = importlib.import_module("swebench.types")
    finally:
        sys.meta_path.remove(finder)
        sys.path.remove(str(root))
    imported = {name: Path(module.__file__).relative_to(root).as_posix()
                for name, module in sys.modules.items()
                if (name == "swebench" or name.startswith("swebench.")) and getattr(module, "__file__", None)}
    return evaluation, reporting, types, imported


def snapshot_files(work):
    """Read closed task-owned files; no semantic classification is performed."""
    work = Path(work)
    result = {}
    for p in sorted(work.rglob("*")):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        if len(raw) > 1024 * 1024:
            raise ValueError("Authored artifact exceeds frozen one-MiB file bound")
        result[p.relative_to(work).as_posix()] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "text": raw.decode("utf-8"),
        }
    return result


def run_case(native, case, run_id, work, journal_path=None):
    """Execute original rewrite/cache and reporting APIs, preserving exceptions."""
    evaluation, reporting, native_types, imported = native
    if case["id"] == "no-native-call":
        return {"operations": [], "artifacts": {}, "closed_writer_artifacts": {},
                "imported_native_modules": imported, "quiescent_handoff": True}
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    journal_path = Path(journal_path).resolve() if journal_path is not None else work / "native-call-journal.jsonl"
    previous = Path.cwd()
    operations, dataset, predictions = [], [], {}
    closed = {}

    def call(name, instance, function, *args, **kwargs):
        with journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(dict(event="entered", operation=name, instance=instance)) + "\n")
        try:
            returned = function(*args, **kwargs)
            if isinstance(returned, Path):
                returned = returned.as_posix()
            if isinstance(returned, tuple):
                returned = list(returned)
            row = dict(operation=name, instance=instance, returned=returned, exception=None)
        except Exception as error:
            row = dict(operation=name, instance=instance, returned=None,
                       exception=dict(type=type(error).__name__, message=str(error)))
        operations.append(row)
        with journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(dict(event="returned", operation=name, instance=instance,
                exception=row["exception"])) + "\n")
        return row

    try:
        os.chdir(work)
        for item in case["instances"]:
            ident = item["id"]
            dataset.append({"instance_id": ident})
            if item.get("prediction", True) is False:
                continue
            prediction = dict(instance_id=ident, model_name_or_path="authored/model",
                              model_patch=item.get("patch", "authored patch"))
            predictions[ident] = prediction
            if not item.get("write", True):
                continue
            directory = Path("logs/run_evaluation") / run_id / "authored__model" / ident
            directory.mkdir(parents=True)
            log = directory / "test_output.txt"
            if not item.get("missing_log"):
                log.write_bytes(item["log"].encode("utf-8"))
            spec = native_types.TestSpec(instance_id=ident, image="unused-in-rewrite-path",
                eval_script_list=[], repo="authored/development", version="1",
                FAIL_TO_PASS=["t::repair"], PASS_TO_PASS=["t::maintain"],
                log_parser="parse_log_pytest", eval_type="pass_and_fail")
            if item.get("unwritable"):
                directory.chmod(0o555)
            try:
                call("rewrite", ident, evaluation.run_instance, spec, prediction, None,
                     run_id, rewrite_reports=True)
            finally:
                if item.get("unwritable"):
                    directory.chmod(0o755)
            report = directory / "report.json"
            if report.exists():
                raw = report.read_bytes()
                closed[report.as_posix()] = dict(sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw), text=raw.decode("utf-8"))
            if item.get("cache"):
                call("cache", ident, evaluation.run_instance, spec, prediction, None,
                     run_id, rewrite_reports=False)
            # Explicit artifact fault controls are not native source repairs.
            if item.get("tamper") == "flip-resolved":
                value = json.loads(report.read_text())
                value[ident]["resolved"] = not value[ident]["resolved"]
                report.write_text(json.dumps(value, indent=4))
            elif item.get("tamper") == "truncate-json":
                report.write_bytes(b"{")
        call("aggregate", "@cohort", reporting.make_run_report, predictions, dataset,
             run_id, client=None)
        return dict(operations=operations, artifacts=snapshot_files(work),
                    closed_writer_artifacts=closed, imported_native_modules=imported,
                    quiescent_handoff=True)
    finally:
        os.chdir(previous)
