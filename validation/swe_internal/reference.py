"""Independent stdlib line/return reference over UNMODIFIED native source.

This program imports no ZeroRun package, declaration, projection, identity
normalizer or verdict implementation. Trace receipts retain original source
lines and raw native locals/returns. Handwritten field extraction below is
separate from the production common projection interpreter.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_driver import load_native, invoke

GRADING = "swebench/harness/grading.py"
PARSER = "swebench/harness/log_parsers/python.py"


def primitive_copy(value):
    if type(value) in (str, int, bool, float) or value is None:
        return value
    if type(value) in (tuple, list):
        return [primitive_copy(x) for x in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: primitive_copy(v) for k, v in value.items()}
    raise ValueError("Not raw primitive native state")


def trace_native(root, native, case, work):
    paths = {str(Path(root) / relative): relative for relative in [GRADING, PARSER]}
    rows, calls, next_call = [], {}, 0

    def trace(frame, event, arg):
        nonlocal next_call
        if frame.f_code.co_filename not in paths:
            return trace
        if event == "call":
            next_call += 1
            calls[id(frame)] = next_call
        if event not in {"call", "line", "return", "exception"}:
            return trace
        values = {}
        for key, value in frame.f_locals.items():
            try:
                values[key] = primitive_copy(value)
            except (ValueError, RecursionError):
                pass
        row = dict(call=calls[id(frame)], path=paths[frame.f_code.co_filename],
                   function=frame.f_code.co_qualname.replace(".<locals>.", "."),
                   line=frame.f_lineno, event=event, locals=values)
        if event == "return":
            row["returned"] = primitive_copy(arg)
        elif event == "exception":
            row["exception"] = arg[0].__name__
        rows.append(row)
        if event == "return":
            del calls[id(frame)]
        return trace

    assert sys.gettrace() is None
    sys.settrace(trace)
    try:
        result = invoke(native, case, work)
    finally:
        sys.settrace(None)
    return result, rows


def reference_sites(version):
    # Independent source-point inventory; it is not read from the observation
    # profile. A wrong production path/index/identity is therefore not copied.
    sites = {
        "parser-return": (PARSER, "parse_log_pytest", "return test_status_map", "return"),
        "parser-write": (PARSER, "parse_log_pytest", "test_status_map[test_case[1]] = test_case[0]", "after"),
        "parser-decision": (PARSER, "parse_log_pytest", "test_status_map[test_case[1]] = test_case[0]", "before"),
        "blocked-return": (GRADING, "get_logs_eval", "return {}, False", "return"),
        "selected-consumed": (GRADING, "get_eval_report", "eval_status_map, found = get_logs_eval(test_spec, test_log_path)", "after"),
        "grading-return": (GRADING, "get_eval_tests_report", "return results", "return"),
        "grading-consumed": (GRADING, "get_eval_report", "report = get_eval_tests_report(eval_status_map, eval_ref, eval_type=eval_type)", "after"),
        "report-return": (GRADING, "get_eval_report", "return report_map", "return"),
        "resolution-f2p": (GRADING, "get_resolution_status", "p2p = compute_pass_to_pass(report)", "after"),
    }
    sites["selected-return"] = (GRADING, "get_logs_eval", "return status_map, True" if version == "after" else "return log_parser(content, test_spec), True", "return")
    if version == "after":
        sites["parser-primary"] = (GRADING, "get_logs_eval", "status_map = log_parser(sliced, test_spec)", "after")
        sites["parser-fallback"] = (GRADING, "get_logs_eval", "status_map = log_parser(content, test_spec)", "after")
    for bank, function in [("f2p", "check_pass_and_fail"), ("p2p", "check_maintained")]:
        for suffix, target in [("success", "success"), ("failure", "failed")]:
            for point, position in [("decision", "before"), ("commit", "after")]:
                sites[bank + "-" + point + "-" + suffix] = (GRADING, "get_eval_tests_report." + function, target + ".append(test_case)", position)
    for status in ["FULL", "PARTIAL", "NO"]:
        sites["resolution-" + status.lower()] = (GRADING, "get_resolution_status", "return ResolvedStatus." + status + ".value", "return")
        sites["resolution-p2p-" + status.lower()] = (GRADING, "get_resolution_status", "return ResolvedStatus." + status + ".value", "before")
    return sites


def source_lines(root, path, function, statement):
    scope = ast.parse((Path(root) / path).read_bytes())
    for name in function.split("."):
        scope, = [n for n in scope.body if isinstance(n, ast.FunctionDef) and n.name == name]
    expected = ast.dump(ast.parse(statement).body[0], include_attributes=False)
    matches = []

    def visit(node):
        if node is not scope and isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.stmt) and ast.dump(node, include_attributes=False) == expected:
            matches.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(scope)
    if not matches:
        raise ValueError("Independent reference source point disappeared")
    return set(matches)


def point_rows(rows, path, function, lines, position):
    selected = [r for r in rows if r["path"] == path and r["function"] == function]
    for index, row in enumerate(selected):
        if row["line"] not in lines:
            continue
        if position == "return" and row["event"] == "line":
            # A with/finally unwind may move f_lineno away from the executed
            # Return before Python emits its return event. Reconcile the actual
            # executed source point with the final native return of this frame.
            following = next((r for r in selected[index + 1:] if r["call"] == row["call"] and r["event"] == "return"), None)
            if following:
                yield following
        elif position == "before" and row["event"] == "line":
            yield row
        elif position == "after" and row["event"] == "line":
            following = next((r for r in selected[index + 1:] if r["call"] == row["call"]), None)
            if following and following["event"] in {"line", "return"}:
                yield following


def fact(site, row):
    """Raw native projection written independently of the observer grammar."""
    state = row["locals"]
    ident = dict(run="s7-swe-development", candidate="authored-control", obligation="@artifact", phase="pipeline", attempt=1)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if site == "parser-return":
        ident["phase"] = "parser"
        values = {"raw": canonical(row["returned"]), "role": "parser"}
    elif site in {"parser-write", "parser-decision"}:
        ident.update(obligation=state["test_case"][1], phase="parser")
        values = {"raw": state["test_status_map"][state["test_case"][1]] if site == "parser-write" else state["test_case"][0],
                  "role": "write" if site == "parser-write" else "decision"}
    elif site in {"parser-primary", "parser-fallback"}:
        values = {"raw": canonical(state["status_map"]), "role": site.split("-")[1]}
        if site == "parser-fallback":
            ident["attempt"] = 2
    elif site in {"selected-return", "blocked-return"}:
        values = {"raw": canonical(row["returned"][0]), "found": row["returned"][1], "role": "selected" if site == "selected-return" else "blocked"}
    elif site == "selected-consumed":
        values = {"raw": canonical(state["eval_status_map"]), "found": state["found"], "role": "selected"}
    elif site.startswith(("f2p-", "p2p-")):
        bank, point, outcome = site.split("-")
        test = state["test_case"]
        ident.update(obligation=test, phase=bank)
        values = {"raw": state["eval_status_map"].get(test, "MISSING"), "test": test,
                  "accepted": outcome == "success", "role": bank}
        if point == "commit":
            values["test"] = state["success" if outcome == "success" else "failed"][-1]
    elif site in {"grading-return", "grading-consumed"}:
        values = {"raw": canonical(row["returned"] if site == "grading-return" else state["report"]), "role": "report"}
    elif site == "resolution-f2p" or site.startswith("resolution-p2p-"):
        ident.update(phase="resolution", obligation="FAIL_TO_PASS" if site == "resolution-f2p" else "PASS_TO_PASS")
        values = {"raw": state["f2p"] if site == "resolution-f2p" else state["p2p"], "role": "native-fraction"}
    elif site.startswith("resolution-"):
        ident.update(phase="resolution", obligation="PASS_TO_PASS")
        values = {"raw": row["returned"], "role": "resolution", "f2p": state["f2p"], "p2p": state["p2p"]}
    elif site == "report-return":
        values = {"raw": canonical(row["returned"]), "role": "serialized"}
    else:
        raise ValueError("Unknown independent reference site")
    return dict(identity=ident, values=values)


def main(options):
    root = Path(options["native_root"])
    hashes = json.loads((Path(options["fixture_root"]) / options["version"] / "source-hashes.json").read_text())
    native = load_native(root, hashes)
    result, rows = trace_native(root, native, options["case"], options["work"])
    facts = {}
    for site, (path, function, statement, position) in reference_sites(options["version"]).items():
        points = point_rows(rows, path, function, source_lines(root, path, function, statement), position)
        facts[site] = [fact(site, row) for row in points]
        for value in facts[site]:
            value["identity"]["run"] = options["run"]
    imported = any(name == "zerorun_harness" or name.startswith("zerorun_harness.") for name in sys.modules)
    if imported:
        raise RuntimeError("Reference imported production framework")
    return dict(native=result, traces=rows, facts=facts, framework_semantics_imported=imported,
        reference_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        native_function_calls=sum(r["event"] == "call" for r in rows),
        native_parser_calls=sum(r["event"] == "call" and r["function"] == "parse_log_pytest" for r in rows))


if __name__ == "__main__":
    config = json.loads(Path(sys.argv[1]).read_text())
    output = main(config)
    with Path(sys.argv[2]).open("x", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2)
