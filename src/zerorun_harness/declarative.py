# SPDX-License-Identifier: MIT
"""Finite, typed native-relationship semantics, independent of extension code.

Domain resources declare source fields and rules. They cannot supply executable
predicates, expected grades, monitor classes or operator implementations.
"""

import copy
from collections import Counter
from functools import wraps

from .api import InvalidEvidence, canonical, digest, fingerprint
from ._vendor import pycontract_core as pc

API = "zerorun.extensions/1"
ENGINE_VERSION = "1.0.0"
TYPES = {"str": str, "int": int, "bool": bool, "float": float}
IDENTITY = {"run", "candidate", "obligation", "phase", "attempt"}


def data_boundary(function):
    """Convert malformed primitive schema failures into an explicit refusal.

    Apply only to non-executing data APIs, never to native code/emitters.
    """

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
            OverflowError,
            UnicodeError,
            RecursionError,
        ) as exc:
            raise InvalidEvidence(
                "Malformed primitive schema at " + function.__name__
            ) from exc

    return wrapped


def require(condition, message):
    if not condition:
        raise InvalidEvidence(message)


def exact(value, keys, what):
    require(
        type(value) is dict and set(value) == set(keys), "Invalid " + what + " fields"
    )


def text(value):
    return type(value) is str and 0 < len(value) <= 256 and value.isprintable()


def typed(value, name):
    return name in TYPES and type(value) is TYPES[name]


def seal(value):
    return {**copy.deepcopy(value), "sha256": digest(value)}


def unseal(value, schema):
    require(
        type(value) is dict
        and value.get("schema") == schema
        and fingerprint(value.get("sha256")),
        "Invalid sealed envelope",
    )
    body = {k: v for k, v in value.items() if k != "sha256"}
    require(digest(body) == value["sha256"], "Envelope digest mismatch")
    return body


@data_boundary
def validate_profile(p):
    canonical(p)
    exact(
        p,
        [
            "api",
            "id",
            "version",
            "identity",
            "facts",
            "sites",
            "rules",
            "justification",
        ],
        "extension profile",
    )
    require(
        p["api"] == API
        and text(p["id"])
        and text(p["version"])
        and text(p["justification"]),
        "Unsupported extension API or identity",
    )
    require(
        type(p["identity"]) is dict
        and IDENTITY <= set(p["identity"])
        and len(p["identity"]) <= 12,
        "Required run/candidate/obligation/phase/attempt identities missing",
    )
    require(
        all(text(k) and v in TYPES for k, v in p["identity"].items()),
        "Invalid identity types",
    )
    require(
        type(p["facts"]) is dict and 1 <= len(p["facts"]) <= 32,
        "Invalid fact inventory",
    )
    for kind, fields in p["facts"].items():
        require(
            text(kind) and type(fields) is dict and 1 <= len(fields) <= 32,
            "Invalid fact fields",
        )
        require(
            all(text(k) and v in TYPES for k, v in fields.items()),
            "Unsupported fact type",
        )
        require(
            not set(fields) & set(p["identity"]),
            "Native values cannot shadow identity fields",
        )
    require(
        type(p["sites"]) is dict and 1 <= len(p["sites"]) <= 64,
        "Invalid site inventory",
    )
    for site, spec in p["sites"].items():
        exact(
            spec,
            [
                "kind",
                "path",
                "function",
                "anchor",
                "position",
                "multiplicity",
                "projection",
                "justification",
            ],
            "site",
        )
        require(
            text(site)
            and spec["kind"] in p["facts"]
            and all(text(spec[k]) for k in ["path", "function", "justification"]),
            "Invalid site identity",
        )
        require(
            type(spec["anchor"]) is str and 0 < len(spec["anchor"]) <= 16384,
            "Invalid source anchor",
        )
        require(
            spec["position"] in ["after", "try_success", "handler_entry"],
            "Unsupported binding position",
        )
        require(
            type(spec["multiplicity"]) is int and 1 <= spec["multiplicity"] <= 16,
            "Invalid static multiplicity",
        )
        require(
            type(spec["projection"]) is dict
            and set(spec["projection"])
            == set(p["identity"]) | set(p["facts"][spec["kind"]]),
            "Incomplete native field projection",
        )
        for value in spec["projection"].values():
            require(
                type(value) is dict and len(value) == 1, "Invalid primitive projection"
            )
            if "local" in value:
                require(
                    type(value["local"]) is str
                    and value["local"].isidentifier()
                    and not value["local"].startswith("__zr_"),
                    "Invalid native local projection",
                )
            else:
                require(
                    set(value) == {"literal"}
                    and type(value["literal"]) in TYPES.values(),
                    "Projection permits only native locals or primitive literals",
                )
    require(
        type(p["rules"]) is list and 1 <= len(p["rules"]) <= 64,
        "Invalid relationship inventory",
    )
    ids = set()
    for r in p["rules"]:
        exact(
            r,
            [
                "id",
                "check",
                "producer",
                "consumer",
                "keys",
                "when",
                "source_field",
                "target_field",
                "operator",
                "statuses",
                "target_mapping",
                "requires",
                "justification",
            ],
            "relationship",
        )
        require(
            text(r["id"]) and r["id"] not in ids and text(r["justification"]),
            "Invalid or duplicate relationship",
        )
        ids.add(r["id"])
        require(
            r["check"] in ["C1", "C2", "C3"]
            and r["producer"] in p["facts"]
            and r["consumer"] in p["facts"],
            "Unsupported relationship",
        )
        require(
            type(r["keys"]) is list
            and len(r["keys"]) == len(set(r["keys"]))
            and set(r["keys"]) <= set(p["identity"]),
            "Invalid matching key",
        )
        require(
            {"run", "candidate", "phase", "attempt"} <= set(r["keys"]),
            "Relationship may not merge native runs/candidates/phases/attempts",
        )
        require(
            r["check"] == "C3" or set(r["keys"]) == set(p["identity"]),
            "C1/C2 require complete native identity",
        )
        require(
            type(r["requires"]) is list
            and len(r["requires"]) == len(set(r["requires"]))
            and set(r["requires"]) <= set(p["sites"]),
            "Invalid coverage dependencies",
        )
        require(
            {r["producer"], r["consumer"]}
            <= {p["sites"][s]["kind"] for s in r["requires"]},
            "Missing producer/consumer coverage dependencies",
        )
        when = r["when"]
        if when is not None:
            exact(when, ["field", "in"], "native disposition")
            require(
                when["field"] in p["facts"][r["producer"]]
                and type(when["in"]) is list
                and 1 <= len(when["in"]) <= 16,
                "Invalid native disposition",
            )
            require(
                all(
                    typed(v, p["facts"][r["producer"]][when["field"]])
                    for v in when["in"]
                ),
                "Disposition type mismatch",
            )
        require(
            type(r["statuses"]) is list and len(r["statuses"]) <= 16,
            "Invalid status set",
        )
        require(
            r["target_mapping"] is None or r["check"] == "C3",
            "Target status mapping is an aggregate policy only",
        )
        if r["check"] == "C1":
            require(
                r["source_field"] is None
                and r["target_field"] is None
                and r["operator"] == "exists"
                and r["statuses"] == [],
                "C1 permits obligation existence only",
            )
        else:
            sf, tf = r["source_field"], r["target_field"]
            require(
                sf in p["facts"][r["producer"]] and tf in p["facts"][r["consumer"]],
                "Unknown native field",
            )
            a, b = p["facts"][r["producer"]][sf], p["facts"][r["consumer"]][tf]
            if r["check"] == "C2":
                require(
                    r["statuses"] == []
                    and r["operator"] in ["identity", "bool_to_int", "int01_to_bool"],
                    "Unsupported native typed conversion",
                )
                require(
                    (r["operator"] == "identity" and a == b)
                    or (r["operator"] == "bool_to_int" and (a, b) == ("bool", "int"))
                    or (r["operator"] == "int01_to_bool" and (a, b) == ("int", "bool")),
                    "Invalid conversion types",
                )
            else:
                require(
                    r["operator"] in ["all", "all_in"], "Unsupported aggregate operator"
                )
                require(
                    (r["operator"] == "all" and a == "bool" and not r["statuses"])
                    or (
                        r["operator"] == "all_in"
                        and r["statuses"]
                        and all(typed(v, a) for v in r["statuses"])
                    ),
                    "Invalid aggregate types",
                )
                mapping = r["target_mapping"]
                if mapping is None:
                    require(
                        b == "bool",
                        "Aggregate target requires boolean or explicit native status mapping",
                    )
                else:
                    exact(
                        mapping,
                        ["true", "false", "incomplete"],
                        "native aggregate status mapping",
                    )
                    require(
                        all(
                            type(values) is list
                            and len(values) <= 16
                            and all(typed(v, b) for v in values)
                            for values in mapping.values()
                        ),
                        "Invalid native status mapping",
                    )
                    flat = [canonical(v) for values in mapping.values() for v in values]
                    require(
                        len(flat) == len(set(flat))
                        and bool(mapping["true"])
                        and bool(mapping["false"]),
                        "Ambiguous native aggregate statuses",
                    )
    return p


def validate_case(p, case):
    exact(
        case,
        ["id", "version", "inventory", "source_sha256", "input_sha256"],
        "case material",
    )
    require(
        text(case["id"])
        and text(case["version"])
        and fingerprint(case["source_sha256"])
        and fingerprint(case["input_sha256"]),
        "Invalid case provenance",
    )
    require(
        type(case["inventory"]) is list and 1 <= len(case["inventory"]) <= 4096,
        "Invalid native inventory",
    )
    seen = set()
    for identity in case["inventory"]:
        exact(identity, p["identity"], "inventory identity")
        require(
            all(typed(identity[k], typ) for k, typ in p["identity"].items()),
            "Native inventory identity type mismatch",
        )
        key = digest(identity)
        require(key not in seen, "Duplicate native inventory identity")
        seen.add(key)


def validate_observations(p, case, events):
    require(type(events) is list and len(events) <= 16384, "Invalid event inventory")
    ids = set()
    sequences = {}
    inventory = {digest(i) for i in case["inventory"]}
    for e in events:
        exact(
            e,
            [
                "id",
                "kind",
                "site",
                "identity",
                "values",
                "producer",
                "seq",
                "source_sha256",
                "binding_sha256",
            ],
            "native event",
        )
        require(text(e["id"]) and e["id"] not in ids, "Invalid or duplicate event id")
        ids.add(e["id"])
        require(
            e["kind"] in p["facts"]
            and e["site"] in p["sites"]
            and p["sites"][e["site"]]["kind"] == e["kind"],
            "Unknown or mismatched native site",
        )
        exact(e["identity"], p["identity"], "event identity")
        require(
            all(typed(e["identity"][k], typ) for k, typ in p["identity"].items()),
            "Native identity type mismatch",
        )
        require(
            digest(e["identity"]) in inventory,
            "Event identity outside declared native inventory",
        )
        exact(e["values"], p["facts"][e["kind"]], "native values")
        require(
            all(typed(e["values"][k], typ) for k, typ in p["facts"][e["kind"]].items()),
            "Native value type mismatch",
        )
        require(
            type(e["producer"]) is int
            and e["producer"] > 0
            and type(e["seq"]) is int
            and e["seq"] > 0,
            "Invalid producer sequence",
        )
        require(
            e["seq"] > sequences.get(e["producer"], 0),
            "Duplicate or nonmonotone producer sequence",
        )
        sequences[e["producer"]] = e["seq"]
        require(
            e["source_sha256"] == case["source_sha256"]
            and fingerprint(e["binding_sha256"]),
            "Native provenance mismatch",
        )


def validate_health(p, h, binding_sha):
    exact(
        h,
        [
            "binding_sha256",
            "sites",
            "transport",
            "native_complete",
            "qualification_sha256",
        ],
        "health",
    )
    require(
        h["binding_sha256"] == binding_sha and fingerprint(h["qualification_sha256"]),
        "Unqualified binding identity",
    )
    exact(h["sites"], p["sites"], "site coverage")
    require(
        all(type(v) is bool or v is None for v in h["sites"].values()),
        "Invalid semantic coverage state",
    )
    require(
        type(h["transport"]) is dict
        and all(
            type(k) is str and k.isdigit() and (type(v) is bool or v is None)
            for k, v in h["transport"].items()
        ),
        "Invalid transport health",
    )
    exact(h["native_complete"], [r["id"] for r in p["rules"]], "native completion")
    require(
        all(type(v) is bool or v is None for v in h["native_complete"].values()),
        "Invalid native completion state",
    )


def key(identity, fields):
    # Identity types are validated before Python tuple equality is used.
    return tuple(identity[k] for k in fields)


def selected(rule, event):
    when = rule["when"]
    return when is None or event["values"][when["field"]] in when["in"]


@data_boundary
def evaluate(profile, case, events, health, binding_sha):
    """Evaluate only declared native relationships; never read adjudication labels."""
    p = validate_profile(profile)
    canonical([case, events, health])
    validate_case(p, case)
    validate_observations(p, case, events)
    validate_health(p, health, binding_sha)
    require(
        all(e["binding_sha256"] == binding_sha for e in events), "Mixed source bindings"
    )
    require(
        {str(e["producer"]) for e in events} <= set(health["transport"]),
        "Missing native producer transport evidence",
    )

    class NativeIndex(pc.Monitor):
        def __init__(self):
            self.by_kind = {kind: [] for kind in p["facts"]}
            super().__init__()

        @pc.initial
        class Read(pc.AlwaysState):
            def transition(self, event):
                self.monitor.by_kind[event["kind"]].append(event)

    monitor = NativeIndex()
    for event in events:
        monitor.eval(event)
    rows = []
    for r in p["rules"]:
        sources = [e for e in monitor.by_kind[r["producer"]] if selected(r, e)]
        targets = monitor.by_kind[r["consumer"]]
        source_groups, target_groups = {}, {}
        for e in sources:
            source_groups.setdefault(key(e["identity"], r["keys"]), []).append(e)
        for e in targets:
            target_groups.setdefault(key(e["identity"], r["keys"]), []).append(e)
        groups = sorted({key(i, r["keys"]) for i in case["inventory"]})
        coverage = all(health["sites"][s] is True for s in r["requires"])
        for group in groups:
            ss, tt = source_groups.get(group, []), target_groups.get(group, [])
            evidence = [e["id"] for e in ss + tt]
            status, reasons = "CONFORMS", []
            duplicate = (
                len(tt) > 1
                or (r["check"] != "C3" and len(ss) > 1)
                or len({digest(e["identity"]) for e in ss}) != len(ss)
            )
            transport = bool(health["transport"]) and all(
                v is True for v in health["transport"].values()
            )
            complete = health["native_complete"][r["id"]] is True
            if duplicate:
                status, reasons = (
                    "INCONCLUSIVE",
                    ["ambiguous_or_duplicate_native_identity"],
                )
            elif not coverage:
                status, reasons = "INCONCLUSIVE", ["unqualified_semantic_sites"]
            elif not ss:
                # A declared skip creates no acceptance/commitment obligation, but
                # absence of a trigger is meaningful only under all premises.
                status = (
                    "CONFORMS"
                    if complete and transport and r["when"] is not None
                    else "INCONCLUSIVE"
                )
                reasons = [
                    "no_applicable_disposition"
                    if status == "CONFORMS"
                    else "missing_native_producer"
                ]
            elif not tt:
                status = (
                    "VIOLATION"
                    if r["check"] == "C1" and complete and transport
                    else "INCONCLUSIVE"
                )
                reasons = [
                    "missing_required_commitment"
                    if status == "VIOLATION"
                    else "missing_native_consumer"
                ]
            elif r["check"] == "C1":
                pass
            elif r["check"] == "C2":
                value = ss[0]["values"][r["source_field"]]
                op = r["operator"]
                if op == "int01_to_bool" and value not in (0, 1):
                    status, reasons = (
                        "UNSUPPORTED",
                        ["native_conversion_outside_qualified_domain"],
                    )
                else:
                    transformed = (
                        int(value)
                        if op == "bool_to_int"
                        else bool(value)
                        if op == "int01_to_bool"
                        else value
                    )
                    target = tt[0]["values"][r["target_field"]]
                    status = (
                        "CONFORMS"
                        if type(transformed) is type(target) and transformed == target
                        else "VIOLATION"
                    )
                    reasons = (
                        []
                        if status == "CONFORMS"
                        else ["witnessed_native_decision_contradiction"]
                    )
            else:
                inventory = {
                    digest(i) for i in case["inventory"] if key(i, r["keys"]) == group
                }
                values = [e["values"][r["source_field"]] for e in ss]
                value = (
                    all(values)
                    if r["operator"] == "all"
                    else all(v in r["statuses"] for v in values)
                )
                # A witnessed false operand determines conjunction even when a
                # native failure-prefix policy leaves later obligations unseen.
                # Missing all-true operands still cannot establish acceptance.
                if {digest(e["identity"]) for e in ss} != inventory and value:
                    status, reasons = "INCONCLUSIVE", ["aggregate_native_inventory_gap"]
                else:
                    observed = tt[0]["values"][r["target_field"]]
                    mapping = r["target_mapping"]
                    if mapping is not None:
                        if observed in mapping["incomplete"]:
                            status, reasons = (
                                "INCONCLUSIVE",
                                ["native_aggregate_incomplete_disposition"],
                            )
                        elif observed not in mapping["true"] + mapping["false"]:
                            status, reasons = (
                                "UNSUPPORTED",
                                ["unknown_native_aggregate_disposition"],
                            )
                        else:
                            observed = observed in mapping["true"]
                            status = "CONFORMS" if observed is value else "VIOLATION"
                            reasons = (
                                []
                                if status == "CONFORMS"
                                else ["witnessed_native_aggregate_contradiction"]
                            )
                    else:
                        status = "CONFORMS" if observed is value else "VIOLATION"
                        reasons = (
                            []
                            if status == "CONFORMS"
                            else ["witnessed_native_aggregate_contradiction"]
                        )
            # Positive qualified witnesses can contradict despite unrelated loss.
            # Successful whole-relation qualification still needs completion.
            if status == "CONFORMS" and (not complete or not transport):
                status, reasons = (
                    "INCONCLUSIVE",
                    ["incomplete_native_or_transport_premise"],
                )
            rows.append(
                dict(
                    relationship=r["id"],
                    check=r["check"],
                    identity=dict(zip(r["keys"], group)),
                    status=status,
                    reasons=reasons,
                    evidence_ids=evidence,
                    required_sites=r["requires"],
                    independently_orderable=False,
                )
            )
    return seal(
        dict(
            schema="zerorun-relationships/1",
            engine_version=ENGINE_VERSION,
            policy_sha256=digest(p),
            binding_sha256=binding_sha,
            case_sha256=digest(case),
            qualification_sha256=health["qualification_sha256"],
            evidence_sha256=digest(events),
            records=rows,
            counts=dict(sorted(Counter(row["status"] for row in rows).items())),
        )
    )
