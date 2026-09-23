"""Original-source stdlib trace reference; no framework or profile imports."""
import ast
import json
from pathlib import Path, PosixPath, WindowsPath
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
if __package__:
    from .native_driver import load_native, run_case
else:
    from native_driver import load_native, run_case

WRITER = "swebench/harness/run_evaluation.py"
REPORTING = "swebench/harness/reporting.py"


def primitive(value):
    if value is None or type(value) in (str, int, bool, float):
        return value
    if type(value) in (list, tuple):
        return [primitive(v) for v in value]
    if type(value) is set:
        return sorted(primitive(v) for v in value)
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: primitive(v) for k, v in value.items()}
    if type(value) in (PosixPath, WindowsPath):
        return {"native_path": value.as_posix()}
    raise ValueError("Nonprimitive native object")


def trace_run(root, native, case, run_id, work, journal_path=None):
    paths = {str(Path(root) / p): p for p in [WRITER, REPORTING,
        "swebench/harness/grading.py", "swebench/harness/log_parsers/python.py"]}
    rows, calls, index = [], {}, 0

    def trace(frame, event, arg):
        nonlocal index
        if frame.f_code.co_filename not in paths:
            return trace
        if event == "call":
            index += 1
            calls[id(frame)] = index
        if event not in ("call", "line", "return", "exception"):
            return trace
        state = {}
        for name, value in frame.f_locals.items():
            try:
                state[name] = primitive(value)
            except (ValueError, RecursionError, TypeError):
                pass
        row = dict(call=calls[id(frame)], path=paths[frame.f_code.co_filename],
            function=frame.f_code.co_qualname.replace(".<locals>.", "."),
            event=event, line=frame.f_lineno, locals=state)
        if event == "return":
            row["returned"] = primitive(arg)
        if event == "exception":
            row["exception"] = arg[0].__name__
        rows.append(row)
        if event == "return":
            del calls[id(frame)]
        return trace

    assert sys.gettrace() is None
    sys.settrace(trace)
    try:
        result = run_case(native, case, run_id, work, journal_path)
    finally:
        sys.settrace(None)
    return result, rows


def site_points():
    # Independent source-point inventory, not loaded from the production policy.
    points = {
        "writer-input": (WRITER, "run_instance", "report = get_eval_report(test_spec=test_spec, prediction=pred, test_log_path=test_output_path, include_tests_status=True)", "after"),
        "writer-write": (WRITER, "run_instance", "f.write(json.dumps(report, indent=4))", "after"),
        "writer-closed": (WRITER, "run_instance", "return instance_id, report", "before"),
        "cache-return": (WRITER, "run_instance", "return instance_id, json.loads(report_path.read_text())", "return"),
        "reader-value": (REPORTING, "make_run_report", "report = json.loads(report_file.read_text())", "after"),
        "derivation-reader": (REPORTING, "make_run_report", "report = json.loads(report_file.read_text())", "after"),
        "aggregate-input": (REPORTING, "make_run_report", "print(json.dumps(report, indent=4), file=f)", "before"),
        "aggregate-written": (REPORTING, "make_run_report", "print(json.dumps(report, indent=4), file=f)", "after"),
        "aggregate-closed": (REPORTING, "make_run_report", "return report_file", "before"),
    }
    categories = ["completed", "resolved", "unresolved", "incomplete", "empty_patch", "error"]
    for category in categories:
        for point in ["decision", "commit"]:
            points[category + "-" + point] = (REPORTING, "make_run_report", category + "_ids.add(instance_id)", "before" if point == "decision" else "after")
    for category in ["completed", "incomplete", "empty_patch", "error"]:
        points["derivation-completed-" + category] = (REPORTING, "make_run_report", category + "_ids.add(instance_id)", "after")
    for category in ["resolved", "unresolved", "incomplete", "empty_patch", "error"]:
        points["resolved-membership-" + category] = (REPORTING, "make_run_report", category + "_ids.add(instance_id)", "after")
    # Locate the actual native aggregate dictionary by its assigned keys, not by
    # a profile-provided AST, and preserve the original complete statement.
    for category in categories:
        for point in ["population", "aggregate"]:
            points[category + "-" + point] = (REPORTING, "make_run_report", "@aggregate-dictionary", "before" if point == "population" else "after")
    for metric in ["total", "submitted"]:
        for point in ["inventory", "reported-inventory"]:
            points[metric + "-" + point] = (REPORTING, "make_run_report", "@aggregate-dictionary", "before" if point == "inventory" else "after")
    return points


def source_points(root, path, function, expression):
    tree = ast.parse((Path(root) / path).read_bytes())
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
    if expression == "@aggregate-dictionary":
        matches = [n for n in ast.walk(function) if isinstance(n, ast.Assign) and
            isinstance(n.value, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "total_instances" for k in n.value.keys)]
        if len(matches) != 1:
            raise ValueError("Native aggregate assignment is ambiguous")
        return {matches[0].lineno: matches[0].end_lineno}
    wanted = ast.dump(ast.parse(expression).body[0], include_attributes=False)
    if path == WRITER and expression in {
        "report = get_eval_report(test_spec=test_spec, prediction=pred, test_log_path=test_output_path, include_tests_status=True)",
        "f.write(json.dumps(report, indent=4))", "return instance_id, report",
    }:
        # Independently select the real rewrite branch. The fresh Docker branch
        # has identical statements but is outside this qualification domain.
        condition, = [n for n in function.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "rewrite_reports"]
        candidates = [n for item in condition.body for n in ast.walk(item)]
    else:
        candidates = ast.walk(function)
    return {n.lineno: n.end_lineno for n in candidates if isinstance(n, ast.stmt) and ast.dump(n, include_attributes=False) == wanted}


def point_rows(rows, path, function, points, position):
    selected = [r for r in rows if r["path"] == path and r["function"] == function]
    completed = set()
    for index, row in enumerate(selected):
        if row["event"] != "line" or row["line"] not in points:
            continue
        if position == "before":
            yield row
        elif position == "after":
            # Multi-line expressions emit line events before the assignment has
            # committed. The reference waits past the whole original statement.
            found = next(((j, r) for j, r in enumerate(selected[index + 1:], index + 1) if r["call"] == row["call"] and
                (r["event"] != "line" or not row["line"] <= r["line"] <= points[row["line"]])), None)
            if found and found[0] not in completed and found[1]["event"] in ("line", "return"):
                completed.add(found[0])
                yield found[1]
        else:
            # Return-expression exception is not a successfully returned value.
            tail = [r for r in selected[index + 1:] if r["call"] == row["call"]]
            following = next((r for r in tail if r["event"] in ("exception", "return")), None)
            if following and following["event"] == "return":
                yield following


def fact(site, row, run):
    state = row["locals"]
    identity = dict(run=run, candidate="authored-reporting", instance=state.get("instance_id", "@cohort"),
                    obligation="report", phase="handoff", attempt=1)
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if site in ("writer-input", "writer-write", "writer-closed", "reader-value"):
        values = dict(raw=encode(state["report"]), role="reader" if site == "reader-value" else site)
    elif site == "cache-return":
        identity["phase"] = "cache"
        values = dict(raw=encode(row["returned"][1]), role="cache")
    elif site.startswith("derivation-completed-"):
        identity.update(phase="resolution", obligation="completed")
        values = dict(raw=state["instance_id"] in state["completed_ids"], role="derivation")
    elif site == "derivation-reader":
        identity.update(phase="resolution", obligation="decision")
        values = dict(raw=state["report"][state["instance_id"]]["resolved"], role="derivation")
    elif site.startswith("resolved-membership-"):
        identity.update(phase="resolution", obligation="decision")
        values = dict(raw=state["instance_id"] in state["resolved_ids"], role="resolved-member")
    elif site in ("aggregate-input", "aggregate-written", "aggregate-closed"):
        identity.update(instance="@cohort", phase="aggregate-file")
        values = dict(raw=encode(state["report"]), role=site)
    elif site.startswith(("total-", "submitted-")):
        metric, point = site.split("-", 1)
        identity.update(instance="@cohort", phase="inventory", obligation=metric)
        count = len(state["full_dataset" if metric == "total" else "predictions"]) if point == "inventory" else state["report"][metric + "_instances"]
        values = dict(count=count, role=point)
    else:
        category, point = site.rsplit("-", 1)
        identity["obligation"] = category
        if point in ("decision", "commit"):
            identity["phase"] = "category"
            values = dict(raw=True if point == "decision" else state["instance_id"] in state[category + "_ids"], role="category-" + point)
        else:
            identity.update(instance="@cohort", phase="aggregate")
            if point == "population":
                raw = sorted(state[category + "_ids"])
                count = len(raw)
            else:
                raw = state["report"][category + "_ids"]
                count = len(raw) if category == "incomplete" else state["report"][category + "_instances"]
            values = dict(raw=encode(raw), count=count, role=point)
    return dict(identity=identity, values=values)


def main(options):
    root = Path(options["native_root"])
    hashes = json.loads((Path(options["fixture_root"]) / options["version"] / "source-hashes.json").read_text())
    native = load_native(root, hashes)
    result, rows = trace_run(root, native, options["case"], options["run"], options["work"], options["call_journal"])
    if Path(options["work"]).exists():
        shutil.copytree(options["work"], options["retained_work"])
    # Persist original results and traces before interpreting source points.
    # A later reference-projection failure cannot erase executed native work.
    with Path(options["raw_reference"]).open("x", encoding="utf-8") as stream:
        json.dump(dict(native=result, traces=rows), stream, indent=2)
    facts = {site: [fact(site, row, options["run"]) for row in point_rows(rows, path, function,
        source_points(root, path, function, expression), position)]
        for site, (path, function, expression, position) in site_points().items()}
    imported = any(n == "zerorun_harness" or n.startswith("zerorun_harness.") for n in sys.modules)
    if imported:
        raise RuntimeError("Reference imported framework")
    return dict(native=result, facts=facts, traces=rows, framework_semantics_imported=False,
                native_function_calls=sum(r["event"] == "call" for r in rows),
                native_calls_by_function={name: sum(r["event"] == "call" and r["function"] == name for r in rows)
                    for name in sorted({r["function"] for r in rows if r["event"] == "call"})})


if __name__ == "__main__":
    options = json.loads(Path(sys.argv[1]).read_text())
    result = main(options)
    with Path(sys.argv[2]).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
