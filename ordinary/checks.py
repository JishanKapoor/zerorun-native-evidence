# SPDX-License-Identifier: MIT
"""Strict ordinary-Python development comparator for the disclosed narrow grammar.

No PyContract imports, verdict inputs, candidate execution, native arithmetic or
claim to support arbitrary histories. Transport and semantic health stay separate.
"""

HEX = set("0123456789abcdef")


def evalplus(obs):
    if not isinstance(obs, dict):
        return "UNSUPPORTED"
    h = obs.get("health")
    if not isinstance(h, dict) or set(h) != {
        "native_complete",
        "transport_intact",
        "semantic_coverage",
    }:
        return "INCONCLUSIVE"
    if any(type(v) is not bool or not v for v in h.values()):
        return "INCONCLUSIVE"
    if (
        type(obs.get("exitcode")) is not int
        or obs["exitcode"] != 0
        or obs.get("outer_timeout") is not False
    ):
        return "INCONCLUSIVE"
    source = obs.get("source_sha256")
    if not isinstance(source, str) or len(source) != 64 or not set(source) <= HEX:
        return "UNSUPPORTED"
    events = obs.get("events")
    seals = obs.get("seals")
    state = obs.get("state")
    if (
        not isinstance(events, list)
        or not isinstance(seals, list)
        or len(seals) != 1
        or not isinstance(state, dict)
    ):
        return "INCONCLUSIVE"
    seal = seals[0]
    if not isinstance(seal, dict) or seal.get("seal") is not True:
        return "INCONCLUSIVE"
    for k in ["attempted", "emitted", "dropped"]:
        if type(seal.get(k)) is not int:
            return "INCONCLUSIVE"
    if (
        seal["dropped"] != 0
        or seal["emitted"] != len(events)
        or seal["attempted"] != len(events)
    ):
        return "INCONCLUSIVE"
    details = state.get("details")
    progress = state.get("progress")
    status = state.get("worker_status")
    if not isinstance(details, list) or any(type(x) is not bool for x in details):
        return "UNSUPPORTED"
    if type(progress) is not int or not 0 <= progress <= len(details):
        return "UNSUPPORTED"
    if type(status) is not int or status not in [0, 1]:
        return "INCONCLUSIVE"
    decisions = {}
    for seq, e in enumerate(events, 1):
        if not isinstance(e, dict):
            return "UNSUPPORTED"
        if type(e.get("seq")) is not int or e["seq"] != seq:
            return "INCONCLUSIVE"
        if type(e.get("optimize")) is not int or e["optimize"] != 0:
            return "UNSUPPORTED"
        i = e.get("index")
        k = e.get("kind")
        if (
            type(i) is not int
            or not 0 <= i < len(details)
            or k not in ["accept", "reject"]
        ):
            return "UNSUPPORTED"
        if i in decisions:
            return "UNSUPPORTED"
        decisions[i] = k == "accept"
    if not decisions:
        return "INCONCLUSIVE"
    if list(decisions) != list(range(len(decisions))):
        return "UNSUPPORTED"
    if progress > len(decisions):
        return "INCONCLUSIVE"
    if progress != len(decisions):
        return "VIOLATION"
    return (
        "CONFORMS"
        if all(details[i] is value for i, value in decisions.items())
        else "VIOLATION"
    )


def swe(obs):
    if not isinstance(obs, dict):
        return "UNSUPPORTED"
    calls = obs.get("parser_calls")
    selected = obs.get("selected")
    if (
        obs.get("observer_coverage") is not True
        or not isinstance(calls, list)
        or not calls
    ):
        return "INCONCLUSIVE"
    if obs.get("found") is not True:
        return "INCONCLUSIVE"
    for mapping in [*calls, selected]:
        if not isinstance(mapping, dict):
            return "UNSUPPORTED"
        if any(
            type(k) is not str
            or type(v) is not str
            or v not in {"PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL"}
            for k, v in mapping.items()
        ):
            return "UNSUPPORTED"
    return "CONFORMS" if calls[-1] == selected else "VIOLATION"
