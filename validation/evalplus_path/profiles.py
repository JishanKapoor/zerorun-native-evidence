"""Finite declarations for one actual EvalPlus parent/child invocation."""

import ast

from evalplus_internal.profiles import worker_profile, IDENTITY, NATIVE_PATH, JUSTIFICATION


def profile(source):
    p = worker_profile(source)
    p["id"], p["version"] = "evalplus-single-invocation-path", "2.0.0"
    for name, site in p["sites"].items():
        site["producer_role"] = "worker"
        if not name.startswith("worker-"):
            site["within"] = [{"header": "for i, inp in enumerate(inputs): pass", "branch": "body"}]

    def identity(index=None):
        return {
            "run": {"context": "run"}, "candidate": {"context": "candidate"},
            "obligation": {"literal": 0} if index is None else index,
            "phase": {"context": "phase"}, "attempt": {"context": "attempt"},
        }

    def add(name, kind, fields, role, function, anchor, position="after", batch=None, index=None, count=1):
        p["facts"][kind] = {key: typ for key, (typ, _) in fields.items()}
        site = dict(kind=kind, path=NATIVE_PATH, function=function, anchor=anchor,
                    position=position, multiplicity=count, producer_role=role,
                    projection={**identity(index), **{k: v[1] for k, v in fields.items()}},
                    justification=JUSTIFICATION)
        if batch:
            site["batch"] = batch
        p["sites"][name] = site

    add("native-child-started", "process_start", {"started": ("bool", {"literal": True})},
        "parent", "untrusted_check", "p.start()")
    add("parent-raw-state", "parent_state",
        {"raw": ("int", {"local": "stat", "path": [{"member": "value"}]})},
        "parent", "untrusted_check", "stat = _mapping[stat.value]", "before")
    add("parent-slice-progress", "parent_progress",
        {"raw": ("int", {"local": "progress", "path": [{"member": "value"}]})},
        "parent", "untrusted_check", "details = details[:progress.value]", "before")
    add("parent-materialized-details", "materialized", {"stored": ("int", {"item": True})},
        "parent", "untrusted_check", "details = details[:progress.value]",
        batch={"local": "details", "max_items": 4096}, index={"ordinal": True})
    add("parent-returned-details", "returned_detail", {"stored": ("int", {"item": True})},
        "parent", "untrusted_check", "return stat, details", "before_return",
        batch={"local": "details", "max_items": 4096}, index={"ordinal": True})
    add("parent-return", "parent", {"raw": ("str", {"local": "stat"})},
        "parent", "untrusted_check", "return stat, details", "before_return")

    worker_nodes = list(ast.walk(next(
        n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "unsafe_execute"
    )))
    for label, anchor in (("loop", "stat.value = _SUCCESS"), ("terminated", "stat.value = _FAILED")):
        add("terminal-progress-" + label, "terminal_progress",
            {"raw": ("int", {"local": "progress", "path": [{"member": "value"}]})},
            "worker", "unsafe_execute", anchor)
    count = sum(isinstance(n, ast.AugAssign) and ast.unparse(n) == "progress.value += 1" for n in worker_nodes)
    add("progress-before-write", "progress_before",
        {"raw": ("int", {"local": "progress", "path": [{"member": "value"}]})},
        "worker", "unsafe_execute", "progress.value += 1", "before",
        index={"local": "i"}, count=count)
    p["sites"]["progress-before-write"]["within"] = [
        {"header": "for i, inp in enumerate(inputs): pass", "branch": "body"}]

    def rule(name, check, producer, consumer, sites, sf=None, tf=None, operator="exists", statuses=None, when=None):
        return dict(id=name, check=check, producer=producer, consumer=consumer,
                    keys=list(IDENTITY), when=when, source_field=sf, target_field=tf,
                    operator=operator, statuses=statuses or [], target_mapping=None,
                    requires=sites, justification=JUSTIFICATION)

    commits = ["true-commit", "false-commit"]
    p["rules"] += [
        rule("commit-preserved-in-parent-element", "C2", "commit", "materialized",
             commits + ["parent-materialized-details"], "stored", "stored", "identity"),
        rule("commit-requires-parent-element", "C1", "commit", "materialized",
             commits + ["parent-materialized-details"]),
        rule("materialized-element-preserved-at-return", "C2", "materialized", "returned_detail",
             ["parent-materialized-details", "parent-returned-details"], "stored", "stored", "identity"),
        rule("worker-progress-preserved-at-parent-slice", "C2", "terminal_progress", "parent_progress",
             ["terminal-progress-loop", "terminal-progress-terminated", "parent-slice-progress"],
             "raw", "raw", "identity"),
    ]
    aggregate = rule("parent-success-from-materialized-inventory", "C3", "returned_detail", "parent",
                     ["parent-returned-details", "parent-return", "parent-raw-state"],
                     "stored", "raw", "all_in", [1])
    aggregate["keys"] = [k for k in IDENTITY if k != "obligation"]
    aggregate["guard"] = {"kind": "parent_state", "field": "raw", "in": [0]}
    aggregate["inventory_policy"] = "complete_batch_membership"
    aggregate["target_mapping"] = {"true": ["pass"], "false": ["fail"], "incomplete": ["timeout"]}
    p["rules"].append(aggregate)
    for label, states, expected, other in (
        ("failure", [1], "fail", ["pass", "timeout"]),
        ("timeout", [2, 3], "timeout", ["pass", "fail"]),
    ):
        mapping = rule("parent-" + label + "-state-mapping", "C3", "parent_state", "parent",
                       ["parent-raw-state", "parent-return"], "raw", "raw", "all_in", states,
                       {"field": "raw", "in": states})
        mapping["target_mapping"] = {"true": [expected], "false": other, "incomplete": []}
        p["rules"].append(mapping)
    return p
