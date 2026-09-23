"""Mechanically bind finite relationships to native source statements."""

import ast

from evalplus_internal.controls import NATIVE_PATH

IDENTITY = {"run": "str", "candidate": "str", "obligation": "int", "phase": "str", "attempt": "int"}
JUSTIFICATION = "Exposed EvalPlus native worker dispositions and actual shared result writes; no candidate mathematical correctness claim"


def _nodes(source, function):
    roots = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function]
    if len(roots) != 1:
        raise ValueError("Unique native function required")
    return list(ast.walk(roots[0]))


def _anchor_count(nodes, text):
    match = ast.dump(ast.parse(text).body[0], include_attributes=False)
    return sum(ast.dump(n, include_attributes=False) == match for n in nodes if isinstance(n, ast.stmt))


def _identity(worker):
    return dict(run={"context": "run"}, candidate={"context": "candidate"}, obligation={"local": "i"} if worker else {"literal": 0}, phase={"context": "phase"}, attempt={"context": "attempt"})


def _rule(ident, check, producer, consumer, sites, source=None, target=None, operator="exists", statuses=None):
    return dict(id=ident, check=check, producer=producer, consumer=consumer, keys=[k for k in IDENTITY if check != "C3" or k != "obligation"], when={"field": "disposition", "in": ["accepted", "caught-rejection"]} if producer == "decision" else None, source_field=source, target_field=target, operator=operator, statuses=statuses or [], target_mapping={"true": ["pass"], "false": ["fail"], "incomplete": ["timeout"]} if check == "C3" else None, requires=sites, justification=JUSTIFICATION)


def worker_profile(source):
    nodes = _nodes(source, "unsafe_execute")
    inner = [n for n in nodes if isinstance(n, ast.Try) and len(n.handlers) == 1 and any(isinstance(x, ast.Assign) and ast.unparse(x) == "details[i] = False" for x in n.handlers[0].body)]
    if len(inner) != 1:
        raise ValueError("Unsupported worker rejection region")
    sites = {}

    def site(name, kind, anchor, values, position="after", count=None, indexed=True):
        sites[name] = dict(kind=kind, path=NATIVE_PATH, function="unsafe_execute", anchor=anchor, position=position, multiplicity=_anchor_count(nodes, anchor) if count is None else count, projection={**_identity(indexed), **values}, justification=JUSTIFICATION)

    for name, anchor in [("accept-exact", "assert exact_match"), ("accept-tolerant", "assert np.allclose(out, exp, rtol=1e-07, atol=atol)"), ("accept-polynomial", "assert abs(_poly(*inp, out)) <= atol")]:
        site(name, "decision", anchor, {"accepted": {"literal": True}, "disposition": {"literal": "accepted"}})
    site("caught-rejection", "decision", ast.unparse(inner[0]), {"accepted": {"literal": False}, "disposition": {"literal": "caught-rejection"}}, "handler_entry", 1)
    site("true-commit", "commit", "details[i] = True", {"stored": {"local": "details", "path": [{"index_local": "i"}]}})
    site("false-commit", "commit", "details[i] = False", {"stored": {"local": "details", "path": [{"index_local": "i"}]}})
    site("progress-write", "progress", "progress.value += 1", {"raw": {"local": "progress", "path": [{"member": "value"}]}})
    site("worker-loop-completed", "worker_state", "stat.value = _SUCCESS", {"raw": {"local": "stat", "path": [{"member": "value"}]}, "meaning": {"literal": "worker_loop_completed"}}, indexed=False)
    site("worker-terminated", "worker_state", "stat.value = _FAILED", {"raw": {"local": "stat", "path": [{"member": "value"}]}, "meaning": {"literal": "worker_terminated"}}, indexed=False)
    decisions = ["accept-exact", "accept-tolerant", "accept-polynomial", "caught-rejection"]
    commits = ["true-commit", "false-commit"]
    rules = [
        _rule("decision-requires-detail", "C1", "decision", "commit", decisions + commits),
        _rule("decision-requires-progress", "C1", "decision", "progress", decisions + ["progress-write"]),
        _rule("decision-preserved-in-shared-byte", "C2", "decision", "commit", decisions + commits, "accepted", "stored", "bool_to_int"),
    ]
    return dict(api="zerorun.extensions/1", id="evalplus-internal-worker", version="1.0.0", identity=IDENTITY, facts={"decision": {"accepted": "bool", "disposition": "str"}, "commit": {"stored": "int"}, "progress": {"raw": "int"}, "worker_state": {"raw": "int", "meaning": "str"}}, sites=sites, rules=rules, justification=JUSTIFICATION)


def parent_profile(source):
    _nodes(source, "untrusted_check")
    # One final native return site; observations do not synthesize parent status.
    site = dict(kind="parent", path=NATIVE_PATH, function="untrusted_check", anchor="return stat, details", position="before_return", multiplicity=1, projection={**_identity(False), "raw": {"local": "stat"}, "details_json": {"local": "details", "encoding": "json"}, "progress": {"local": "progress", "path": [{"member": "value"}]}}, justification=JUSTIFICATION)
    # C3 joins the direct worker and separate full-parent acquisitions explicitly.
    p = worker_profile(source)
    p["id"] = "evalplus-internal-worker-parent"
    p["facts"]["parent"] = {"raw": "str", "details_json": "str", "progress": "int"}
    p["sites"]["parent-return"] = site
    p["rules"].append(_rule("committed-details-to-parent", "C3", "commit", "parent", ["true-commit", "false-commit", "parent-return"], "stored", "raw", "all_in", [1]))
    return p
