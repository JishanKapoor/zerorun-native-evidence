"""Separate native reference: unmodified source, CPython tracing, raw shared state.

This module intentionally imports no ZeroRun production code or profile generator.
The line-transition reference observes the original worker statements and actual
shared-memory values; it never derives an expected event from an observer event.
"""

import ast
import hashlib
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import sys


def _identity(i, case):
    return dict(run="exposed-native-worker", candidate=case["id"], obligation=i, phase="base", attempt=1)


def trace_recipe(source):
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "unsafe_execute")
    actions = {}
    rejection_lines = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if handler.body and any(isinstance(n, ast.Assign) and ast.unparse(n) == "details[i] = False" for n in ast.walk(handler)):
                    rejection_lines.add(handler.body[0].lineno)
        if not isinstance(node, ast.stmt):
            continue
        text = ast.unparse(node)
        sites = {
            "assert exact_match": "accept-exact",
            "assert np.allclose(out, exp, rtol=1e-07, atol=atol)": "accept-tolerant",
            "assert abs(_poly(*inp, out)) <= atol": "accept-polynomial",
            "details[i] = True": "true-commit",
            "details[i] = False": "false-commit",
            "progress.value += 1": "progress-write",
            "stat.value = _SUCCESS": "worker-loop-completed",
            "stat.value = _FAILED": "worker-terminated",
        }
        if text in sites:
            actions[node.lineno] = (sites[text], node.end_lineno)
    return actions, rejection_lines


def reference_run(native_root, case, output, source_override=None):
    if source_override:
        dependencies = json.loads(Path(source_override).with_name("native-dependencies.json").read_text())
        for path, expected_sha in dependencies.items():
            if hashlib.sha256((Path(native_root) / path).read_bytes()).hexdigest() != expected_sha:
                raise ValueError("Pinned native dependency changed: " + path)
    sys.path.insert(0, str(native_root))
    native = importlib.import_module("evalplus.eval")
    source_path = Path(native_root) / "evalplus/eval/__init__.py"
    source = Path(source_override or source_path).read_bytes().decode("utf-8")
    exec(compile(source, str(source_path), "exec"), native.__dict__)
    kwargs = dict(dataset="humaneval", code=case["code"], inputs=case["inputs"], entry_point=case["entry"], expected=case["expected"], atol=case["atol"], ref_time=[0.001] * len(case["inputs"]), fast_check=case["fast"], min_time_limit=0.08, gt_time_limit_factor=4)
    if case.get("preflight_error"):
        kwargs["ref_time"] = ["invalid"]
        try:
            native.untrusted_check(**kwargs)
        except TypeError:
            result = dict(schema="evalplus-independent-preflight-reference/1", exception="TypeError", facts={"parent-return": []}, native_bank_calls=0, framework_semantics_imported=any(name == "zerorun_harness" or name.startswith("zerorun_harness.") for name in sys.modules))
        else:
            raise AssertionError("Native preflight rejection was not observed")
        with open(output, "x", encoding="utf-8") as stream:
            json.dump(result, stream)
        return
    parent_observations = []
    parent_return_metadata = []
    def parent_trace(frame, event, argument):
        if frame.f_code is not native.untrusted_check.__code__:
            return None
        if event == "return" and type(argument) is tuple and len(argument) == 2:
            parent_observations.append(dict(identity=_identity(0, case), values=dict(raw=argument[0], details_json=json.dumps(argument[1], separators=(",", ":")), progress=int(frame.f_locals["progress"].value))))
            parent_return_metadata.append(dict(line=frame.f_lineno, parent_pid=os.getpid(), native_worker_pid=frame.f_locals["p"].pid, event="native_return"))
        return parent_trace
    sys.settrace(parent_trace)
    grade, parent_details = native.untrusted_check(**kwargs)
    sys.settrace(None)
    assert len(parent_observations) == 1
    parent = {"grade": grade, "details": [int(v) for v in parent_details]}
    stat = multiprocessing.Value("i", native._UNKNOWN)
    details = multiprocessing.Array("b", [False] * len(case["inputs"]))
    progress = multiprocessing.Value("i", 0)
    actions, rejections = trace_recipe(source)
    facts = {name: [] for name in ["accept-exact", "accept-tolerant", "accept-polynomial", "caught-rejection", "true-commit", "false-commit", "progress-write", "worker-loop-completed", "worker-terminated", "parent-return"]}
    facts["parent-return"].extend(parent_observations)
    pending = [None]
    exceptions = []
    transitions = []

    def record(site, local, source_line, observation_line, phase):
        index = 0 if site.startswith("worker-") else local["i"]
        if site.startswith("accept-"):
            values = dict(accepted=True, disposition="accepted")
        elif site == "caught-rejection":
            values = dict(accepted=False, disposition="caught-rejection")
        elif site in ("true-commit", "false-commit"):
            values = dict(stored=int(local["details"][index]))
        elif site == "progress-write":
            values = dict(raw=int(local["progress"].value))
        else:
            values = dict(raw=int(local["stat"].value), meaning="worker_loop_completed" if site == "worker-loop-completed" else "worker_terminated")
        facts[site].append(dict(identity=_identity(index, case), values=values))
        transitions.append(dict(site=site, source_line=source_line, observation_line=observation_line, phase=phase, identity=_identity(index, case), values=values, native_worker_pid=os.getpid()))

    def trace(frame, event, argument):
        if frame.f_code is not native.unsafe_execute.__code__:
            return None
        if event == "exception":
            pending[0] = None
            exceptions.append(dict(line=frame.f_lineno, exception=argument[0].__name__, obligation=frame.f_locals.get("i"), raw_details=[int(v) for v in frame.f_locals["details"]], raw_progress=int(frame.f_locals["progress"].value)))
        elif event in ("line", "return"):
            previous = pending[0]
            if previous and (event == "return" or not previous[1] <= frame.f_lineno <= previous[2]):
                record(previous[0], frame.f_locals, previous[1], frame.f_lineno, "post_statement_without_exception")
                pending[0] = None
            if event == "line":
                if frame.f_lineno in rejections:
                    record("caught-rejection", frame.f_locals, frame.f_lineno, frame.f_lineno, "native_handler_entry")
                if frame.f_lineno in actions:
                    site, end = actions[frame.f_lineno]
                    pending[0] = (site, frame.f_lineno, end)
        return trace

    # Open the retained output before the actual native reliability guard.
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    write, close = os.write, os.close
    sys.settrace(trace)
    native.unsafe_execute("humaneval", case["entry"], case["code"], case["inputs"], case["expected"], [0.08] * len(case["inputs"]), case["atol"], case["fast"], stat, details, progress)
    sys.settrace(None)
    result = dict(schema="evalplus-independent-native-reference/1", native_source_sha256=hashlib.sha256(source.encode()).hexdigest(), framework_semantics_imported=any(name == "zerorun_harness" or name.startswith("zerorun_harness.") for name in sys.modules), facts=facts, exceptions=exceptions, transitions=transitions, parent_return_metadata=parent_return_metadata, worker=dict(stat=int(stat.value), details=[int(v) for v in details], progress=int(progress.value)), parent=parent, native_bank_calls=2, reference_method="Original native worker executed with CPython line/exception transitions; actual shared values and separate original native parent execution")
    payload = json.dumps(result, sort_keys=True).encode()
    written = 0
    while written < len(payload):
        written += write(descriptor, payload[written:])
    close(descriptor)


if __name__ == "__main__":
    reference_run(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
