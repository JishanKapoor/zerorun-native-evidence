# SPDX-License-Identifier: MIT
"""Separately implemented PyContract checker; consumes primitive saved evidence.

Schema/health checks are duplicated deliberately to avoid importing the ordinary
comparator as the semantic oracle. Scope matches pilot_checks, not full R11.
"""

from ._vendor import pycontract_core as pc


def evalplus(data):
    if type(data) != dict:
        return "UNSUPPORTED"
    flags = data.get("health", {})
    if type(flags) != dict or set(flags) != set(
        ["native_complete", "transport_intact", "semantic_coverage"]
    ):
        return "INCONCLUSIVE"
    if tuple(
        flags[k] is True
        for k in ["native_complete", "transport_intact", "semantic_coverage"]
    ) != (True, True, True):
        return "INCONCLUSIVE"
    if (
        data.get("outer_timeout") is not False
        or type(data.get("exitcode")) is not int
        or data["exitcode"] != 0
    ):
        return "INCONCLUSIVE"
    fingerprint = data.get("source_sha256", "")
    if (
        type(fingerprint) != str
        or len(fingerprint) != 64
        or any(c not in "0123456789abcdef" for c in fingerprint)
    ):
        return "UNSUPPORTED"
    stream = data.get("events")
    ends = data.get("seals")
    native = data.get("state")
    if (
        type(stream) != list
        or type(ends) != list
        or len(ends) != 1
        or type(native) != dict
    ):
        return "INCONCLUSIVE"
    end = ends[0]
    if type(end) != dict or end.get("seal") is not True:
        return "INCONCLUSIVE"
    if any(type(end.get(k)) != int for k in ("attempted", "emitted", "dropped")):
        return "INCONCLUSIVE"
    if (end["attempted"], end["emitted"], end["dropped"]) != (
        len(stream),
        len(stream),
        0,
    ):
        return "INCONCLUSIVE"
    cells = native.get("details")
    p = native.get("progress")
    status = native.get("worker_status")
    if type(cells) != list or any(type(c) != bool for c in cells):
        return "UNSUPPORTED"
    if type(p) != int or p < 0 or p > len(cells):
        return "UNSUPPORTED"
    if type(status) != int or status not in (0, 1):
        return "INCONCLUSIVE"
    identities = []
    for n, e in enumerate(stream):
        if type(e) != dict:
            return "UNSUPPORTED"
        if type(e.get("seq")) != int or e["seq"] != n + 1:
            return "INCONCLUSIVE"
        if type(e.get("optimize")) != int or e["optimize"] != 0:
            return "UNSUPPORTED"
        i = e.get("index")
        if (
            type(i) != int
            or i < 0
            or i >= len(cells)
            or e.get("kind") not in ("accept", "reject")
        ):
            return "UNSUPPORTED"
        if i in identities:
            return "UNSUPPORTED"
        identities.append(i)
    if len(identities) == 0:
        return "INCONCLUSIVE"
    if identities != list(range(len(identities))):
        return "UNSUPPORTED"
    # A committed prefix longer than the observed disposition prefix is an
    # observation gap. It cannot establish a native commitment contradiction.
    if p > len(identities):
        return "INCONCLUSIVE"

    class Commit(pc.Monitor):
        def __init__(self):
            self.seen = {}
            self.violation = False
            super().__init__()

        @pc.initial
        class Read(pc.AlwaysState):
            def transition(self, e):
                m = self.monitor
                if e["kind"] == "terminal":
                    m.violation = (e["progress"] != len(m.seen)) or any(
                        e["details"][i] is not val for i, val in m.seen.items()
                    )
                else:
                    m.seen[e["index"]] = e["kind"] == "accept"

    m = Commit()
    for event in stream:
        m.eval(event)
    # Native metadata is data, never a source of monitor control fields.
    m.eval({"kind": "terminal", "progress": p, "details": cells})
    return "VIOLATION" if m.violation else "CONFORMS"


def swe(data):
    if type(data) != dict:
        return "UNSUPPORTED"
    stream = data.get("parser_calls")
    if (
        data.get("observer_coverage") is not True
        or type(stream) != list
        or len(stream) == 0
        or data.get("found") is not True
    ):
        return "INCONCLUSIVE"
    all_maps = stream + [data.get("selected")]
    for value in all_maps:
        if type(value) != dict:
            return "UNSUPPORTED"
        for identity, status in value.items():
            if (
                type(identity) != str
                or type(status) != str
                or status not in ("PASSED", "FAILED", "ERROR", "SKIPPED", "XFAIL")
            ):
                return "UNSUPPORTED"

    class Selection(pc.Monitor):
        def __init__(self):
            self.last = None
            self.violation = False
            super().__init__()

        @pc.initial
        class Read(pc.AlwaysState):
            def transition(self, e):
                if e["terminal"]:
                    self.monitor.violation = self.monitor.last != e["value"]
                else:
                    self.monitor.last = e["value"]

    m = Selection()
    for v in stream:
        m.eval({"terminal": False, "value": v})
    m.eval({"terminal": True, "value": data["selected"]})
    return "VIOLATION" if m.violation else "CONFORMS"
