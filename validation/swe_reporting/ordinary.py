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
    return dict(handoffs=handoffs, aggregate_checks=aggregates,
                actual_final_file_preserved=files, framework_imports=False,
                native_calls=0, scope="Direct original execution and file/trace assertions; no independent investigator claim")
