"""Finite declarations for exposed native SWE pytest parser/grading paths.

This file declares no executable verdict or expected grade. Native source bytes
remain external, pinned upstream material. The test names are authored controls.
"""

GRADING = "swebench/harness/grading.py"
PARSER = "swebench/harness/log_parsers/python.py"
REVISIONS = {
    "before": "a5ecda6640d13f89848a3dceaa08585431d258db",
    "after": "489a34eb8c99f123e6af5f3ea8f3a8e8db85710b",
}
IDENTITY = {"run": "str", "candidate": "str", "obligation": "str", "phase": "str", "attempt": "int"}
F2P = "tests/test_control.py::test_repair"
P2P = "tests/test_control.py::test_maintenance"
STATUSES = ["PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL", "XPASS", "MISSING"]


def literal(value):
    return {"literal": value}


def local(name, *indices, encoding=None, default=None):
    result = {"local": name}
    if indices:
        result["path"] = [{"index": i} if not isinstance(i, dict) else i for i in indices]
    if encoding:
        result["encoding"] = encoding
    if default is not None:
        result["default"] = default
    return result


def returned(*indices, encoding=None):
    result = {"return": True}
    if indices:
        result["path"] = [{"index": i} for i in indices]
    if encoding:
        result["encoding"] = encoding
    return result


def profile(version):
    assert version in REVISIONS
    p = dict(api="zerorun.extensions/1", id="swe-internal-" + version, version="1.0.0",
             identity=IDENTITY.copy(), facts={}, sites={}, rules=[],
             justification="Exposed native pytest parser selection, F2P/P2P decisions, commitment, report and resolution paths")

    def site(name, kind, function, anchor, position, fields, types=None,
             path=GRADING, obligation="@artifact", phase="pipeline", attempt=1, multiplicity=1):
        projection = {"run": {"context": "run"}, "candidate": {"context": "candidate"},
                      "obligation": obligation if isinstance(obligation, dict) else literal(obligation),
                      "phase": literal(phase), "attempt": literal(attempt), **fields}
        p["facts"][kind] = types or {field: "str" for field in fields}
        p["sites"][name] = dict(kind=kind, path=path, function=function, anchor=anchor,
            position=position, multiplicity=multiplicity, projection=projection,
            justification="Observe existing native state at " + name + "; callback supplies no evaluator decision")

    # Parser writes retain raw line status and committed map value separately.
    # Parser invocation output is observed at the actual native return.
    site("parser-return", "parser-return", "parse_log_pytest", "return test_status_map", "return_value",
         {"raw": returned(encoding="json"), "role": literal("parser")}, path=PARSER, phase="parser")
    site("parser-write", "parser-write", "parse_log_pytest",
         "test_status_map[test_case[1]] = test_case[0]", "after",
         {"raw": local("test_status_map", {"index_local": "test_case", "index_path": [1]}), "role": literal("write")}, path=PARSER,
         obligation=local("test_case", 1), phase="parser")
    site("parser-decision", "parser-decision", "parse_log_pytest",
         "test_status_map[test_case[1]] = test_case[0]", "before",
         {"raw": local("test_case", 0), "role": literal("decision")}, path=PARSER,
         obligation=local("test_case", 1), phase="parser")
    for check, name, sf, tf, operator in [("C1", "parser-required-store", None, None, "exists"),
                                         ("C2", "parser-status-preserved", "raw", "raw", "identity")]:
        p["rules"].append(dict(id=name, check=check, producer="parser-decision", consumer="parser-write",
            keys=list(IDENTITY), when={"field": "role", "in": ["decision"]}, source_field=sf, target_field=tf,
            operator=operator, statuses=[], target_mapping=None, requires=["parser-decision", "parser-write"],
            justification="Native parser's selected raw status requires the same actual dictionary cell after its original store"))
    # Maps remain immutable snapshots. First and fallback invocations are distinct
    # facts; neither is renamed the selected final return map.
    if version == "after":
        site("parser-primary", "parser-primary", "get_logs_eval", "status_map = log_parser(sliced, test_spec)", "after",
             {"raw": local("status_map", encoding="json"), "role": literal("primary")})
        site("parser-fallback", "parser-fallback", "get_logs_eval", "status_map = log_parser(content, test_spec)", "after",
             {"raw": local("status_map", encoding="json"), "role": literal("fallback")}, attempt=2)
        selection_anchor = "return status_map, True"
    else:
        selection_anchor = "return log_parser(content, test_spec), True"
    site("selected-return", "selected", "get_logs_eval", selection_anchor, "return_value",
         {"raw": returned(0, encoding="json"), "found": returned(1), "role": literal("selected")},
         types={"raw": "str", "found": "bool", "role": "str"})
    site("blocked-return", "blocked", "get_logs_eval", "return {}, False", "return_value",
         {"raw": returned(0, encoding="json"), "found": returned(1), "role": literal("blocked")},
         types={"raw": "str", "found": "bool", "role": "str"}, multiplicity=2)
    site("selected-consumed", "selection-consumed", "get_eval_report",
         "eval_status_map, found = get_logs_eval(test_spec, test_log_path)", "after",
         {"raw": local("eval_status_map", encoding="json"), "found": local("found"), "role": literal("selected")},
         types={"raw": "str", "found": "bool", "role": "str"})

    for bank, function, successful in [
        ("f2p", "check_pass_and_fail", ["PASSED", "XFAIL"]),
        ("p2p", "check_maintained", ["PASSED", "XFAIL", "SKIPPED"]),
    ]:
        for outcome, target in [(True, "success"), (False, "failed")]:
            suffix = "success" if outcome else "failure"
            anchor = target + ".append(test_case)"
            fn = "get_eval_tests_report." + function
            values = {"raw": local("eval_status_map", {"index_local": "test_case"}, default="MISSING"),
                      "test": local("test_case"), "accepted": literal(outcome), "role": literal(bank)}
            types = {"raw": "str", "test": "str", "accepted": "bool", "role": "str"}
            site(bank + "-decision-" + suffix, bank + "-decision", fn, anchor, "before", values, types,
                 obligation=local("test_case"), phase=bank)
            committed = {**values, "test": local(target, -1)}
            site(bank + "-commit-" + suffix, bank + "-commit", fn, anchor, "after", committed, types,
                 obligation=local("test_case"), phase=bank)

        for check, label, sf, tf, operator, statuses in [
            ("C1", "required-commit", None, None, "exists", []),
            ("C2", "identity-preserved", "test", "test", "identity", []),
            ("C3", "native-status-policy", "raw", "accepted", "all_in", successful),
        ]:
            p["rules"].append(dict(id=bank + "-" + label, check=check,
                producer=bank + "-decision", consumer=bank + "-commit", keys=list(IDENTITY),
                when={"field": "role", "in": [bank]}, source_field=sf, target_field=tf, operator=operator,
                statuses=statuses, target_mapping=None,
                requires=[bank + "-" + point + "-" + result for point in ["decision", "commit"] for result in ["success", "failure"]],
                justification="Native " + bank + " branch decides disposition; original list append commits the same test identity"))

    site("grading-return", "grading-return", "get_eval_tests_report", "return results", "return_value",
         {"raw": returned(encoding="json"), "role": literal("report")})
    site("grading-consumed", "grading-consumed", "get_eval_report",
         "report = get_eval_tests_report(eval_status_map, eval_ref, eval_type=eval_type)", "after",
         {"raw": local("report", encoding="json"), "role": literal("report")})
    site("resolution-f2p", "resolution-input", "get_resolution_status", "p2p = compute_pass_to_pass(report)", "after",
         {"raw": local("f2p"), "role": literal("native-fraction")}, types={"raw": "float", "role": "str"},
         phase="resolution", obligation="FAIL_TO_PASS")
    for resolution in ["FULL", "PARTIAL", "NO"]:
        site("resolution-p2p-" + resolution.lower(), "resolution-input", "get_resolution_status",
             "return ResolvedStatus." + resolution + ".value", "before_return",
             {"raw": local("p2p"), "role": literal("native-fraction")}, types={"raw": "float", "role": "str"},
             phase="resolution", obligation="PASS_TO_PASS")
        site("resolution-" + resolution.lower(), "resolution", "get_resolution_status",
             "return ResolvedStatus." + resolution + ".value", "return_value",
             {"raw": returned(), "role": literal("resolution"), "f2p": local("f2p"), "p2p": local("p2p")},
             types={"raw": "str", "role": "str", "f2p": "float", "p2p": "float"},
             phase="resolution", obligation="PASS_TO_PASS")
    p["rules"].append(dict(id="resolution-native-aggregate", check="C3", producer="resolution-input", consumer="resolution",
        keys=["run", "candidate", "phase", "attempt"], when={"field": "role", "in": ["native-fraction"]},
        source_field="raw", target_field="raw", operator="all_in", statuses=[1.0],
        target_mapping={"true": ["RESOLVED_FULL"], "false": ["RESOLVED_PARTIAL", "RESOLVED_NO"], "incomplete": []},
        requires=["resolution-f2p"] + ["resolution-p2p-" + v for v in ["full", "partial", "no"]]
                 + ["resolution-" + v for v in ["full", "partial", "no"]],
        justification="Native FULL requires both original native F2P and P2P fractions equal one; PARTIAL and NO are not full resolution"))
    site("report-return", "report-return", "get_eval_report", "return report_map", "return_value",
         {"raw": returned(encoding="json"), "role": literal("serialized")}, multiplicity=3)

    for label, producer, consumer, role, sites in [
        ("selection-preserved", "selected", "selection-consumed", "selected", ["selected-return", "selected-consumed"]),
        ("blocked-preserved", "blocked", "selection-consumed", "blocked", ["blocked-return", "selected-consumed"]),
        ("grading-preserved", "grading-return", "grading-consumed", "report", ["grading-return", "grading-consumed"]),
    ]:
        p["rules"].append(dict(id=label, check="C2", producer=producer, consumer=consumer,
            keys=list(IDENTITY), when={"field": "role", "in": [role]}, source_field="raw", target_field="raw",
            operator="identity", statuses=[], target_mapping=None, requires=sites,
            justification="Preserve actual native returned values across their caller consumption boundary"))
    return p


def case_definitions():
    """Prospective authored artifacts; these are not previously unused cases."""
    return [
        dict(id="passed", statuses=["PASSED", "PASSED"], layout="inside"),
        dict(id="repair-failed", statuses=["FAILED", "PASSED"], layout="inside"),
        dict(id="maintenance-failed", statuses=["PASSED", "FAILED"], layout="inside"),
        dict(id="expected-failure", statuses=["XFAIL", "PASSED"], layout="inside"),
        dict(id="both-skipped", statuses=["SKIPPED", "SKIPPED"], layout="inside"),
        dict(id="repair-error", statuses=["ERROR", "PASSED"], layout="inside"),
        dict(id="missing-repair", statuses=[None, "PASSED"], layout="inside"),
        dict(id="fallback", statuses=["PASSED", "PASSED"], layout="outside"),
        dict(id="missing-markers", statuses=["PASSED", "PASSED"], layout="missing"),
        dict(id="bad-code", statuses=["PASSED", "PASSED"], layout="bad"),
        dict(id="none-patch", statuses=["PASSED", "PASSED"], layout="inside", patch_is_none=True),
        dict(id="partial", statuses=["PASSED", "PASSED"], layout="inside", second_repair="FAILED"),
        dict(id="skip-summary", statuses=["PASSED", "PASSED"], layout="inside", extra="SKIPPED [1] tests/test_unrelated.py:4: reason"),
    ]
