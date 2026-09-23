# SPDX-License-Identifier: MIT
"""Ordinary relational comparator: no production framework or PyContract import.

Accepts the disclosed already-validated primitive grammar. Data/schema admission
is tested separately. This is a semantic cross-check, not an external engine.
Guards, producer-scoped premises and raw batch population closure are interpreted
here without importing production normalizers, batch receipts or verdicts.
"""

import json


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _need(condition, message):
    if not condition:
        raise ValueError("Ordinary native batch: " + message)


def _populations(profile, events, health):
    """Read the raw begin/element/end stream, not a production completeness flag.

    Each producer owns a serial stream. Only a matching end and every actual
    position close its population. A later ordinary event/new begin terminates
    an unfinished population without erasing its positive element evidence.
    """
    admitted = {event["id"]: _wire(event) for event in events}
    opened, populations, beginnings, event_ids = {}, [], set(), set()
    for entry in health["batch_journal"]:
        if entry.get("schema") == "zerorun-acquisition-lifecycle/1":
            continue
        is_boundary = entry.get("schema") == "zerorun-native-batch/1"
        site, producer = entry["site"], entry["producer"]
        _need(site in profile["sites"] and type(producer) is int and producer > 0,
              "unknown site/producer")
        spec = profile["sites"][site]
        _need(entry["binding_sha256"] == health["binding_sha256"], "binding mismatch")
        _need(str(producer) in health["transport"], "missing producer transport")
        if "producers" in health:
            _need(health["producers"][spec["producer_role"]] == producer, "role mismatch")
        if is_boundary:
            _need(set(entry) == {"schema", "site", "producer", "binding_sha256", "batch", "size", "stage", "identity"},
                  "unexpected boundary fields")
            _need("batch" in spec and type(entry["batch"]) is int and entry["batch"] > 0
                  and type(entry["size"]) is int and 0 <= entry["size"] <= spec["batch"]["max_items"],
                  "invalid batch identity or size")
            fields = {key for key in profile["identity"]
                      if not ({"item", "ordinal"} & set(spec["projection"][key]))}
            _need(set(entry["identity"]) == fields, "invalid group fields")
            kinds = {"int": int, "str": str, "float": float, "bool": bool}
            _need(all(type(value) is kinds[profile["identity"][key]]
                      for key, value in entry["identity"].items()), "invalid group types")
            if entry["stage"] == "begin":
                marker = (producer, entry["batch"])
                _need(marker not in beginnings, "repeated batch identity")
                beginnings.add(marker)
                if producer in opened:
                    populations.append(opened.pop(producer))
                opened[producer] = {"begin": entry, "positions": [], "ids": [], "closed": False}
            else:
                _need(entry["stage"] == "end" and producer in opened, "unmatched end")
                population = opened.pop(producer)
                first = population["begin"]
                _need(all(_wire(first[key]) == _wire(entry[key]) for key in ("site", "batch", "size", "identity")),
                      "end changed population")
                population["closed"] = (population["positions"] == list(range(entry["size"]))
                                         and len(population["ids"]) == entry["size"])
                populations.append(population)
            continue
        _need(entry["id"] not in event_ids and admitted.get(entry["id"]) == _wire(entry),
              "journal event differs from admitted observation")
        event_ids.add(entry["id"])
        if "batch" not in spec:
            if producer in opened:
                populations.append(opened.pop(producer))
            continue
        _need(producer in opened and opened[producer]["begin"]["site"] == site,
              "element without matching begin")
        population = opened[producer]
        _need(all(type(entry["identity"][key]) is type(value) and entry["identity"][key] == value
                  for key, value in population["begin"]["identity"].items()), "element changed group")
        if spec["batch"].get("ordinal") == "acquisition":
            acquired = entry["acquisition"]
            _need(set(acquired) == {"batch", "ordinal"}
                  and acquired["batch"] == population["begin"]["batch"], "wrong acquisition batch")
            position = acquired["ordinal"]
        else:
            fields = [key for key in profile["identity"] if spec["projection"][key] == {"ordinal": True}]
            position = entry["identity"][fields[0]]
            _need(all(entry["identity"][key] == position for key in fields), "ordinal identity disagreement")
        _need(type(position) is int, "noninteger position")
        population["positions"].append(position)
        population["ids"].append(entry["id"])
    return populations + list(opened.values())


def run(profile, case, events, health):
    output = []
    serialize = _wire
    populations = _populations(profile, events, health) if "batch_journal" in health else []
    for rule in profile["rules"]:
        involved = set(rule["requires"])
        if "producers" in health or "guard" in rule:
            kinds = {rule["producer"], rule["consumer"]}
            if "guard" in rule:
                kinds.add(rule["guard"]["kind"])
            involved.update(site for site, value in profile["sites"].items() if value["kind"] in kinds)
        coverage = all(health["sites"][site] is True for site in involved)
        complete = health["native_complete"][rule["id"]] is True
        if "producers" in health:
            roles = {profile["sites"][site]["producer_role"] for site in involved}
            transport = all(health["producers"][role] is not None
                            and health["transport"][str(health["producers"][role])] is True for role in roles)
        else:
            transport = bool(health["transport"]) and all(value is True for value in health["transport"].values())
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
            guards = [event for event in matching if event["kind"] == rule.get("guard", {}).get("kind")]
            batches = [population for population in populations
                       if profile["sites"][population["begin"]["site"]]["kind"] == rule["producer"]
                       and tuple(population["begin"]["identity"][key] for key in rule["keys"]) == group] if "inventory_policy" in rule else []
            closed = (len(batches) == 1 and batches[0]["closed"]
                      and set(batches[0]["ids"]) == {event["id"] for event in source}
                      and complete and transport)
            if "guard" in rule and len(guards) != 1:
                status = "INCONCLUSIVE"
            elif not coverage:
                status = "INCONCLUSIVE"
            elif "guard" in rule and guards[0]["values"][rule["guard"]["field"]] not in rule["guard"]["in"]:
                status = "CONFORMS"
            elif (
                len(target) > 1
                or (rule["check"] != "C3" and len(source) > 1)
                or len({serialize(e["identity"]) for e in source}) != len(source)
            ):
                status = "INCONCLUSIVE"
            elif not source and not closed:
                status = (
                    "CONFORMS"
                    if rule["when"] is not None
                    and complete and transport
                    else "INCONCLUSIVE"
                )
            elif not target:
                status = (
                    "VIOLATION"
                    if rule["check"] == "C1"
                    and complete and transport
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
                population_equal = {serialize(e["identity"]) for e in source} == required
                if not population_equal and value and not closed:
                    status = "INCONCLUSIVE"
                else:
                    if closed:
                        value = value and population_equal
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
                not complete or not transport
            ):
                status = "INCONCLUSIVE"
            output.append((rule["id"], group, status))
    return output
