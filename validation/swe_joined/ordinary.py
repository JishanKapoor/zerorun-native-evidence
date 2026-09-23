"""Direct raw-reference/file assertions, with no common checker import."""
import json


def check(reference):
    native = reference["native"]
    writer = {r["instance"]: r["returned"][1] for r in native["operations"]
              if r["operation"] == "rewrite" and r["exception"] is None}
    consumed = {}
    final_states = []
    for row in reference["traces"]:
        if row["function"] != "make_run_report" or row["event"] != "line":
            continue
        if row["line"] == 65:
            consumed[row["locals"]["instance_id"]] = row["locals"]["report"]
        if row["line"] == 118:
            final_states.append(row["locals"])
    handoffs = {ident: {"writer_present": ident in writer,
                       "preserved": writer.get(ident) == value}
                for ident, value in consumed.items()}
    aggregates = []
    for state in final_states:
        report = state["report"]
        checks = {"total": report["total_instances"] == len(state["full_dataset"]),
                  "submitted": report["submitted_instances"] == len(state["predictions"])}
        for category in ["completed", "resolved", "unresolved", "incomplete", "empty_patch", "error"]:
            population = sorted(state[category + "_ids"])
            checks[category + "_population"] = report[category + "_ids"] == population
            if category != "incomplete":
                checks[category + "_count"] = report[category + "_instances"] == len(population)
        checks["resolved_membership_from_native_reader"] = all(
            (ident in state["resolved_ids"]) is bool(value[ident]["resolved"])
            and ident in state["completed_ids"] for ident, value in consumed.items())
        aggregates.append(checks)
    files = []
    for row in native["operations"]:
        if row["operation"] == "aggregate" and row["exception"] is None:
            raw = native["artifacts"][row["returned"]]
            files.append(json.loads(raw["text"]) == final_states[-1]["report"])
    # Independent assertions over returns and stored locals of this one native
    # invocation. These are never loaded from the declarative fact extractor.
    internal_checks = []
    returns = {name: [r for r in reference['traces'] if r['event'] == 'return' and r['function'] == name]
               for name in ['get_eval_tests_report', 'get_resolution_status', 'get_eval_report']}
    for row in returns['get_eval_tests_report']:
        state, report = row['locals'], row['returned']
        for bank, key in [('f2p','FAIL_TO_PASS'),('p2p','PASS_TO_PASS')]:
            for outcome in ['success','failure']:
                internal_checks.append(dict(name=bank + '-' + outcome + '-committed-list-to-report',
                    passed=state[bank + '_' + outcome] == report[key][outcome]))
    for row in returns['get_eval_report']:
        report = row['returned']
        entry = report[row['locals']['instance_id']]
        if 'tests_status' in entry:
            internal_checks.append(dict(name='grading-to-embedded-tests',
                passed=len(returns['get_eval_tests_report']) == 1 and entry['tests_status'] == returns['get_eval_tests_report'][0]['returned']))
            internal_checks.append(dict(name='native-resolution-to-reported-boolean',
                passed=len(returns['get_resolution_status']) == 1
                and entry['resolved'] is (returns['get_resolution_status'][0]['returned'] == 'RESOLVED_FULL')))
        consumed_reports = [r['locals']['report'] for r in reference['traces'] if r['function'] == 'run_instance'
                            and r['event'] == 'line' and r['line'] == 181]
        internal_checks.append(dict(name='grader-return-to-native-writer-input',
            # CPython emits the same with-header on entry and normal exit.
            # Both are reads in one native call, not two writer invocations.
            passed=bool(consumed_reports) and all(report == value for value in consumed_reports)))
    return dict(handoffs=handoffs, aggregate_checks=aggregates,
                actual_final_file_preserved=files, internal_checks=internal_checks, framework_imports=False,
                native_calls=0, scope="Direct original execution and file/trace assertions; no independent investigator claim")
