"""Independent raw internal field extraction, adapted from the exposed S7 reference.
No native invocations and no framework imports occur in this module.
"""

import json

GRADING = "swebench/harness/grading.py"

PARSER = "swebench/harness/log_parsers/python.py"

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
