"""Finite source-derived relationships for real upstream saved-log reporting."""

WRITER = "swebench/harness/run_evaluation.py"
REPORTING = "swebench/harness/reporting.py"
REVISIONS = {"before": "a5ecda6640d13f89848a3dceaa08585431d258db",
             "after": "489a34eb8c99f123e6af5f3ea8f3a8e8db85710b"}
CATEGORIES = ["completed", "resolved", "unresolved", "incomplete", "empty_patch", "error"]
IDENTITY = dict(run="str", candidate="str", instance="str", obligation="str", phase="str", attempt="int")


def lit(value):
    return {"literal": value}


def local(name, *indices, **options):
    result = {"local": name, **options}
    if indices:
        result["path"] = [{"index": v} if not isinstance(v, dict) else v for v in indices]
    return result


def profile(version):
    p = dict(api="zerorun.extensions/1", id="swe-reporting-" + version, version="1.0.0",
             identity=IDENTITY.copy(), facts={}, sites={}, rules=[],
             justification="Original upstream rewrite writer, file reader, category commitment and aggregate reporting")

    def site(name, kind, path, function, anchor, position, values, types, *,
             phase="handoff", obligation="report", instance=None, multiplicity=1):
        p["facts"][kind] = types
        p["sites"][name] = dict(kind=kind, path=path, function=function, anchor=anchor,
            position=position, multiplicity=multiplicity,
            projection=dict(run={"context": "run"}, candidate={"context": "candidate"},
                instance=instance or local("instance_id"), obligation=lit(obligation),
                phase=lit(phase), attempt=lit(1), **values),
            justification="Observe actual native source state at " + name)

    def rule(name, check, producer, consumer, sf=None, tf=None, when=None, requires=None, keys=None):
        p["rules"].append(dict(id=name, check=check, producer=producer, consumer=consumer,
            keys=keys or list(IDENTITY), when=when or {"field": "role", "in": [producer]},
            source_field=sf, target_field=tf, operator="exists" if check == "C1" else "all" if check == "C3" else "identity",
            statuses=[], target_mapping=None, requires=requires or [s for s, v in p["sites"].items() if v["kind"] in [producer, consumer]],
            justification="Preserve qualified native " + name))

    raw_types = {"raw": "str", "role": "str"}
    writer_call = "report = get_eval_report(test_spec=test_spec, prediction=pred, test_log_path=test_output_path, include_tests_status=True)"
    for name, kind, anchor, position in [
        ("writer-input", "writer-input", writer_call, "after"),
        ("writer-write", "writer-write", 'f.write(json.dumps(report, indent=4))', "after"),
        ("writer-closed", "writer-closed", "return instance_id, report", "before_return"),
    ]:
        site(name, kind, WRITER, "run_instance", anchor, position,
             dict(raw=local("report", encoding="json"), role=lit(kind)), raw_types)
        p["sites"][name]["within"] = [{"header": "if rewrite_reports: pass", "branch": "body"}]
    site("cache-return", "cache", WRITER, "run_instance",
         "return instance_id, json.loads(report_path.read_text())", "return_value",
         dict(raw={"return": True, "path": [{"index": 1}], "encoding": "json"}, role=lit("cache")), raw_types,
         phase="cache")
    site("reader-value", "reader", REPORTING, "make_run_report",
         "report = json.loads(report_file.read_text())", "after",
         dict(raw=local("report", encoding="json"), role=lit("reader")), raw_types)
    rule("writer-required-write", "C1", "writer-input", "writer-write")
    rule("writer-write-preservation", "C2", "writer-input", "writer-write", "raw", "raw")
    rule("writer-required-close", "C1", "writer-write", "writer-closed")
    rule("writer-close-preservation", "C2", "writer-write", "writer-closed", "raw", "raw")
    # The native reader determines which report is consumed; empty/missing
    # predictions do not invent a requirement to consume a writer artifact.
    rule("consumed-report-preserves-closed-writer", "C2", "reader", "writer-closed", "raw", "raw")

    for category in CATEGORIES:
        variable = category + "_ids"
        anchor = variable + ".add(instance_id)"
        for point in ["decision", "commit"]:
            kind = "category-" + point
            site(category + "-" + point, kind, REPORTING, "make_run_report", anchor,
                 "before" if point == "decision" else "after",
                 dict(raw=lit(True) if point == "decision" else local(variable, contains={"local": "instance_id"}), role=lit(kind)),
                 {"raw": "bool", "role": "str"}, phase="category", obligation=category)
    rule("category-required-commit", "C1", "category-decision", "category-commit")
    rule("category-membership-preservation", "C2", "category-decision", "category-commit", "raw", "raw")

    # These are actual native premises and actual membership, not expected grades.
    for category in ["completed", "incomplete", "empty_patch", "error"]:
        site("derivation-completed-" + category, "derivation", REPORTING, "make_run_report",
             category + "_ids.add(instance_id)", "after",
             dict(raw=local("completed_ids", contains={"local": "instance_id"}), role=lit("derivation")),
             {"raw": "bool", "role": "str"}, phase="resolution", obligation="completed")
    site("derivation-reader", "derivation", REPORTING, "make_run_report",
         "report = json.loads(report_file.read_text())", "after",
         dict(raw=local("report", {"index_local": "instance_id"}, "resolved"), role=lit("derivation")),
         {"raw": "bool", "role": "str"}, phase="resolution", obligation="decision")
    for category in ["resolved", "unresolved", "incomplete", "empty_patch", "error"]:
        site("resolved-membership-" + category, "resolved-member", REPORTING, "make_run_report",
             category + "_ids.add(instance_id)", "after",
             dict(raw=local("resolved_ids", contains={"local": "instance_id"}), role=lit("resolved-member")),
             {"raw": "bool", "role": "str"}, phase="resolution", obligation="decision")
    rule("native-resolution-derivable", "C3", "derivation", "resolved-member", "raw", "raw",
         keys=[k for k in IDENTITY if k != "obligation"])

    aggregate_anchor = '''report = {
        "total_instances": len(full_dataset), "submitted_instances": len(predictions),
        "completed_instances": len(completed_ids), "resolved_instances": len(resolved_ids),
        "unresolved_instances": len(unresolved_ids), "empty_patch_instances": len(empty_patch_ids),
        "error_instances": len(error_ids), "completed_ids": list(sorted(completed_ids)),
        "incomplete_ids": list(sorted(incomplete_ids)), "empty_patch_ids": list(sorted(empty_patch_ids)),
        "submitted_ids": list(sorted(predictions.keys())), "resolved_ids": list(sorted(resolved_ids)),
        "unresolved_ids": list(sorted(unresolved_ids)), "error_ids": list(sorted(error_ids)), "schema_version": 2}'''
    for category in CATEGORIES:
        for point in ["population", "aggregate"]:
            kind = point
            if point == "population":
                fields = dict(raw=local(category + "_ids", encoding="sorted_json"),
                              count=local(category + "_ids", size=True))
            else:
                fields = dict(raw=local("report", category + "_ids", encoding="json"),
                    count=local("report", "incomplete_ids", size=True) if category == "incomplete" else local("report", category + "_instances"))
            site(category + "-" + point, kind, REPORTING, "make_run_report", aggregate_anchor,
                 "before" if point == "population" else "after", dict(**fields, role=lit(kind)),
                 {"raw": "str", "count": "int", "role": "str"}, phase="aggregate", obligation=category, instance=lit("@cohort"))
    rule("aggregate-required-population", "C1", "population", "aggregate")
    rule("aggregate-population-preserved", "C2", "population", "aggregate", "raw", "raw")
    rule("aggregate-cardinality-preserved", "C2", "population", "aggregate", "count", "count")
    for metric, variable in [("total", "full_dataset"), ("submitted", "predictions")]:
        for point in ["inventory", "reported-inventory"]:
            site(metric + "-" + point, point, REPORTING, "make_run_report", aggregate_anchor,
                 "before" if point == "inventory" else "after",
                 dict(count=local(variable, size=True) if point == "inventory" else local("report", metric + "_instances"), role=lit(point)),
                 {"count": "int", "role": "str"}, phase="inventory", obligation=metric, instance=lit("@cohort"))
    rule("aggregate-input-denominator-preserved", "C2", "inventory", "reported-inventory", "count", "count")
    for point, position, anchor in [("input", "before", 'print(json.dumps(report, indent=4), file=f)'),
                                     ("written", "after", 'print(json.dumps(report, indent=4), file=f)'),
                                     ("closed", "before_return", "return report_file")]:
        kind = "aggregate-" + point
        site(kind, kind, REPORTING, "make_run_report", anchor, position,
             dict(raw=local("report", encoding="json"), role=lit(kind)), raw_types,
             phase="aggregate-file", instance=lit("@cohort"))
    rule("aggregate-file-required-write", "C1", "aggregate-input", "aggregate-written")
    rule("aggregate-file-required-close", "C1", "aggregate-written", "aggregate-closed")
    rule("aggregate-file-value-preserved", "C2", "aggregate-input", "aggregate-closed", "raw", "raw")
    return p


def case_definitions():
    def log(first="PASSED", second="PASSED", layout="inside"):
        body = first + " t::repair\n" + second + " t::maintain\n"
        markers = ">>>>> Start Test Output\n", ">>>>> End Test Output\n"
        return body if layout == "missing" else body + markers[0] + "runner\n" + markers[1] if layout == "outside" else markers[0] + body + markers[1]

    def item(ident="a", **kwargs):
        return dict(id=ident, log=log(), **kwargs)

    return [
        dict(id="resolved", instances=[item()]),
        dict(id="unresolved", instances=[dict(id="a", log=log("FAILED"))]),
        dict(id="mixed-population", instances=[item("a"), dict(id="b", log=log("FAILED")),
            item("c", patch="", write=False), item("d", prediction=False),
            item("e", write=False), item("f", patch=None)]),
        dict(id="fallback", instances=[dict(id="a", log=log(layout="outside"))]),
        dict(id="missing-markers", instances=[dict(id="a", log=log(layout="missing"))]),
        dict(id="cached-report", instances=[item(cache=True)]),
        dict(id="missing-log", instances=[item(missing_log=True)]),
        dict(id="write-denied", instances=[item(unwritable=True)]),
        dict(id="changed-file", instances=[item(tamper="flip-resolved")]),
        dict(id="truncated-file", instances=[item(tamper="truncate-json")]),
        dict(id="no-native-call", instances=[]),
    ]


def case_inventory(case, run):
    """Population from declared inputs, never from emitted/reference outcomes."""
    if case["id"] == "no-native-call":
        return []
    result = []

    def add(instance, phase, obligation):
        result.append(dict(run=run, candidate="authored-reporting", instance=instance,
                           phase=phase, obligation=obligation, attempt=1))

    for item in case["instances"]:
        instance = item["id"]
        add(instance, "handoff", "report")
        add(instance, "cache", "report")
        for category in CATEGORIES:
            add(instance, "category", category)
        # Both native conjunction operands remain declared even if a callback
        # or independent reference fails to retain one of them.
        add(instance, "resolution", "completed")
        add(instance, "resolution", "decision")
    for category in CATEGORIES:
        add("@cohort", "aggregate", category)
    for metric in ["total", "submitted"]:
        add("@cohort", "inventory", metric)
    add("@cohort", "aggregate-file", "report")
    return result
