"""Independent original-source, one-parent-invocation CPython reference.

No framework observer, mapper, profile generator or checker is imported. Opcode
transitions discriminate a completed native store from a false-initialized cell.
"""

import ast
import dis
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

MAX_JOURNAL = 8 * 1024 * 1024


def recipe(source):
    worker = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "unsafe_execute")
    operations, rejections = {}, set()
    labels = {
        "details[i] = True": "true-commit",
        "details[i] = False": "false-commit",
        "progress.value += 1": "progress-write",
        "stat.value = _SUCCESS": "worker-loop-completed",
        "stat.value = _FAILED": "worker-terminated",
        "assert exact_match": "accept-exact",
        "assert np.allclose(out, exp, rtol=1e-07, atol=atol)": "accept-tolerant",
        "assert abs(_poly(*inp, out)) <= atol": "accept-polynomial",
    }
    for node in ast.walk(worker):
        if isinstance(node, ast.stmt) and ast.unparse(node) in labels:
            operations[node.lineno] = (labels[ast.unparse(node)], node.end_lineno)
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if handler.body and any(
                    isinstance(n, ast.Assign) and ast.unparse(n) == "details[i] = False"
                    for n in handler.body
                ):
                    rejections.add(handler.body[0].lineno)
    parent = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "untrusted_check")
    parent_lines = {}
    for node in ast.walk(parent):
        if isinstance(node, ast.stmt):
            text = ast.unparse(node)
            if text in ("p.start()", "stat = _mapping[stat.value]", "details = details[:progress.value]"):
                parent_lines[text] = (node.lineno, node.end_lineno)
    return operations, rejections, parent_lines


def run(prepared, case, output, run_id, *, original_root=None, source_inventory=None):
    output.mkdir(parents=True, exist_ok=False)
    root = prepared / "original" if original_root is None else original_root
    inventory = json.loads((prepared / "original-files.json").read_text()) if source_inventory is None else source_inventory
    for name, expected in inventory.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Original native dependency changed: " + name)
    sys.dont_write_bytecode = True
    sys.pycache_prefix = str(output / "unused-bytecode")
    sys.path.insert(0, str(root))
    native = importlib.import_module("evalplus.eval")
    if Path(native.__file__).resolve() != (root / "evalplus/eval/__init__.py").resolve():
        raise ValueError("Original native module origin mismatch")
    source = Path(native.__file__).read_bytes().decode()
    operations, rejection_lines, parent_lines = recipe(source)
    bytecode = {i.offset: i for i in dis.get_instructions(native.unsafe_execute)}
    parent_pid = os.getpid()
    descriptors = {
        "parent": os.open(output / "parent.jsonl", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
        "worker": os.open(output / "worker.jsonl", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
    }
    write, close, getpid, getppid = os.write, os.close, os.getpid, os.getppid
    role = ["parent"]
    count, size, lost = [0], [0], [False]
    pending_store, pending_assert, pending_parent = [None], [None], [None]
    native_started = [False]

    def after_parent():
        close(descriptors["worker"])
        descriptors["worker"] = None

    def after_child():
        role[0] = "worker"
        close(descriptors["parent"])
        descriptors["parent"] = None
        count[0] = size[0] = 0
        lost[0] = False
        pending_store[0] = pending_assert[0] = pending_parent[0] = None

    os.register_at_fork(after_in_parent=after_parent, after_in_child=after_child)

    def identity(index=0):
        return dict(run=run_id, candidate=case["id"], obligation=index, phase="base", attempt=1)

    def record(name, frame, values=None, index=0, proof="source_transition", source_line=None):
        count[0] += 1
        row = dict(sequence=count[0], name=name, pid=getpid(), parent_pid=getppid(),
                   source_line=frame.f_lineno if source_line is None else source_line,
                   observation_line=frame.f_lineno, bytecode_offset=frame.f_lasti,
                   identity=identity(index), values=values or {}, proof=proof)
        payload = (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode()
        if size[0] + len(payload) > MAX_JOURNAL:
            lost[0] = True
            return
        offset = 0
        try:
            while offset < len(payload):
                written = write(descriptors[role[0]], payload[offset:])
                if written <= 0:
                    lost[0] = True
                    return
                offset += written
            size[0] += len(payload)
        except OSError:
            lost[0] = True

    def worker_fact(name, frame, proof, source_line):
        local = frame.f_locals
        index = 0 if name.startswith("worker-") else local.get("i", 0)
        if name.startswith("accept-"):
            values = {"accepted": True, "disposition": "accepted"}
        elif name == "caught-rejection":
            values = {"accepted": False, "disposition": "caught-rejection"}
        elif name in ("true-commit", "false-commit"):
            values = {"stored": int(local["details"][index])}
        elif name in ("progress-write", "progress-before-write"):
            values = {"raw": int(local["progress"].value)}
        else:
            values = {"raw": int(local["stat"].value),
                      "meaning": "worker_loop_completed" if name == "worker-loop-completed" else "worker_terminated"}
        record(name, frame, values, index, proof, source_line)
        if name.startswith("worker-"):
            label = "terminal-progress-loop" if name == "worker-loop-completed" else "terminal-progress-terminated"
            record(label, frame, {"raw": int(local["progress"].value)}, 0, proof, source_line)

    def trace(frame, event, argument):
        if frame.f_code is native.unsafe_execute.__code__:
            frame.f_trace_opcodes = True
            if event == "call":
                record("native-worker-entry", frame, {"input_count": len(frame.f_locals["inputs"])})
            elif event == "exception":
                pending_store[0] = pending_assert[0] = None
                record("native-worker-exception", frame,
                       {"exception": type.__getattribute__(argument[0], "__name__")},
                       frame.f_locals.get("i", 0), "actual_exception_transition")
            elif event == "opcode":
                if pending_store[0]:
                    name, line, operation = pending_store[0]
                    worker_fact(name, frame, "completed_" + operation, line)
                    pending_store[0] = None
                instruction = bytecode.get(frame.f_lasti)
                if instruction and instruction.opname in ("STORE_SUBSCR", "STORE_ATTR"):
                    line = instruction.positions.lineno
                    if line in operations and not operations[line][0].startswith("accept-"):
                        pending_store[0] = (operations[line][0], line, instruction.opname)
            elif event in ("line", "return"):
                if pending_assert[0]:
                    name, first, last = pending_assert[0]
                    if event == "return" or not first <= frame.f_lineno <= last:
                        worker_fact(name, frame, "passed_native_assertion", first)
                        pending_assert[0] = None
                if event == "line":
                    line = frame.f_lineno
                    if line in rejection_lines:
                        worker_fact("caught-rejection", frame, "actual_handler_entry", line)
                    if line in operations:
                        name, end = operations[line]
                        if name.startswith("accept-"):
                            pending_assert[0] = (name, line, end)
                        elif name == "progress-write":
                            worker_fact("progress-before-write", frame, "before_native_update", line)
                else:
                    instruction = bytecode.get(frame.f_lasti)
                    record("native-worker-return", frame, {"journal_lost": lost[0],
                           "normal_return": instruction is not None and instruction.opname == 'RETURN_VALUE'},
                           proof="original_function_return_transition")
            return trace
        if frame.f_code is native.untrusted_check.__code__:
            if event in ("line", "return"):
                if pending_parent[0]:
                    name, first, last = pending_parent[0]
                    if event == "return" or not first <= frame.f_lineno <= last:
                        if name == "p.start()":
                            native_started[0] = True
                            record("native-child-started", frame, {"started": True}, source_line=first)
                            record("native-process-identity", frame, {"child_pid": frame.f_locals["p"].pid})
                        else:
                            details = frame.f_locals["details"]
                            record("native-materialized-batch", frame, {"details": list(details), "size": len(details)}, source_line=first)
                            for index, value in enumerate(details):
                                record("parent-materialized-details", frame, {"stored": int(value)}, index, source_line=first)
                        pending_parent[0] = None
                if event == "line":
                    for name, (first, last) in parent_lines.items():
                        if frame.f_lineno != first:
                            continue
                        if name == "stat = _mapping[stat.value]":
                            record("parent-raw-state", frame, {"raw": int(frame.f_locals["stat"].value)})
                            process = frame.f_locals['p']
                            backend = object.__getattribute__(process,'__dict__')['_popen']
                            cached = object.__getattribute__(backend,'__dict__')
                            record('native-process-finished',frame,{'child_pid':cached['pid'],
                                   'cached_exitcode':cached['returncode']},proof='native_cached_state_no_poll_or_wait')
                        elif name == "details = details[:progress.value]":
                            record("parent-slice-progress", frame, {"raw": int(frame.f_locals["progress"].value)})
                            pending_parent[0] = (name, first, last)
                        else:
                            pending_parent[0] = (name, first, last)
                elif type(argument) is tuple and len(argument) == 2:
                    record("parent-return", frame, {"raw": argument[0]})
                    record("native-returned-batch", frame, {"details": list(argument[1]), "size": len(argument[1])})
                    for index, value in enumerate(argument[1]):
                        record("parent-returned-details", frame, {"stored": int(value)}, index)
            elif event == "exception":
                pending_parent[0] = None
                record("native-parent-exception", frame,
                       {"exception": type.__getattribute__(argument[0], "__name__")})
            return trace
        return None

    kwargs = dict(dataset="humaneval", code=case["code"], inputs=case["inputs"],
                  entry_point=case["entry"], expected=case["expected"], atol=case["atol"],
                  ref_time=["invalid"] if case.get("preflight_error") else [0.001] * len(case["inputs"]),
                  fast_check=case["fast"], min_time_limit=0.08, gt_time_limit_factor=4)
    returned, exception = None, None
    sys.settrace(trace)
    try:
        status, details = native.untrusted_check(**kwargs)
        returned = {"grade": status, "details": list(details)}
    except BaseException as exc:
        exception = type.__getattribute__(type(exc), "__name__")
    finally:
        sys.settrace(None)
        for fd in descriptors.values():
            if fd is not None:
                close(fd)
    rows = {}
    for label in ("parent", "worker"):
        rows[label] = [json.loads(line) for line in (output / (label + ".jsonl")).read_text().splitlines()]
    result = dict(schema="s8-evalplus-one-call-reference/1", returned=returned, exception=exception,
                  parent_pid=parent_pid, journal=rows, parent_journal_lost=lost[0],
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  native_bank_calls=int(native_started[0]),
                  framework_semantics_imported=any(n == "zerorun_harness" or n.startswith("zerorun_harness.") for n in sys.modules),
                  recipe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with (output / "reference.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return result


if __name__ == "__main__":
    result = run(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3]), sys.argv[4])
    print(json.dumps({"returned": result["returned"], "exception": result["exception"],
                      "native_bank_calls": result["native_bank_calls"]}))
