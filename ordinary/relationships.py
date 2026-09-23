# SPDX-License-Identifier: MIT
"""Ordinary relational comparator: no production framework or PyContract import.

Accepts the disclosed already-validated primitive grammar. Data/schema admission
is tested separately. This is a semantic cross-check, not an external engine.
"""

import json


def run(profile, case, events, health):
    output = []
    serialize = lambda obj: json.dumps(
        obj, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    for rule in profile["rules"]:
        groups = sorted({tuple(i[k] for k in rule["keys"]) for i in case["inventory"]})
        for group in groups:
            matching = [
                e
                for e in events
                if tuple(e["identity"][k] for k in rule["keys"]) == group
            ]
            source = []
            for e in matching:
                if e["kind"] != rule["producer"]:
                    continue
                guard = rule["when"]
                if guard is None or e["values"][guard["field"]] in guard["in"]:
                    source.append(e)
            target = [e for e in matching if e["kind"] == rule["consumer"]]
            if (
                len(target) > 1
                or (rule["check"] != "C3" and len(source) > 1)
                or len({serialize(e["identity"]) for e in source}) != len(source)
            ):
                status = "INCONCLUSIVE"
            elif any(health["sites"][s] is not True for s in rule["requires"]):
                status = "INCONCLUSIVE"
            elif not source:
                status = (
                    "CONFORMS"
                    if rule["when"] is not None
                    and health["native_complete"][rule["id"]] is True
                    and health["transport"]
                    and all(v is True for v in health["transport"].values())
                    else "INCONCLUSIVE"
                )
            elif not target:
                status = (
                    "VIOLATION"
                    if rule["check"] == "C1"
                    and health["native_complete"][rule["id"]] is True
                    and health["transport"]
                    and all(v is True for v in health["transport"].values())
                    else "INCONCLUSIVE"
                )
            elif rule["check"] == "C1":
                status = "CONFORMS"
            elif rule["check"] == "C2":
                a = source[0]["values"][rule["source_field"]]
                b = target[0]["values"][rule["target_field"]]
                if rule["operator"] == "int01_to_bool" and a not in (0, 1):
                    status = "UNSUPPORTED"
                else:
                    if rule["operator"] == "bool_to_int":
                        a = 1 if a else 0
                    if rule["operator"] == "int01_to_bool":
                        a = a == 1
                    status = (
                        "CONFORMS" if type(a) is type(b) and a == b else "VIOLATION"
                    )
            else:
                required = {
                    serialize(i)
                    for i in case["inventory"]
                    if tuple(i[k] for k in rule["keys"]) == group
                }
                value = True
                for event in source:
                    item = event["values"][rule["source_field"]]
                    value = value and (
                        item if rule["operator"] == "all" else item in rule["statuses"]
                    )
                if {serialize(e["identity"]) for e in source} != required and value:
                    status = "INCONCLUSIVE"
                else:
                    observed = target[0]["values"][rule["target_field"]]
                    mapping = rule["target_mapping"]
                    if mapping is not None and observed in mapping["incomplete"]:
                        status = "INCONCLUSIVE"
                    elif (
                        mapping is not None
                        and observed not in mapping["true"] + mapping["false"]
                    ):
                        status = "UNSUPPORTED"
                    else:
                        if mapping is not None:
                            observed = observed in mapping["true"]
                        status = "CONFORMS" if observed is value else "VIOLATION"
            if status == "CONFORMS" and (
                health["native_complete"][rule["id"]] is not True
                or not health["transport"]
                or any(v is not True for v in health["transport"].values())
            ):
                status = "INCONCLUSIVE"
            output.append((rule["id"], group, status))
    return output
