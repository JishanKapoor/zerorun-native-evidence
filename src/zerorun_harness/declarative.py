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
from .projection import validate_projection

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
        {k:v for k,v in p.items() if k != "record_types"},
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
    if "record_types" in p:
        require(type(p["record_types"]) is dict and 1 <= len(p["record_types"]) <= 16,
                "Invalid native record inventory")
        for ident,record in p["record_types"].items():
            exact(record,["module","name","path","fields"],"native record declaration")
            require(text(ident) and type(record["module"]) is str
                    and all(part.isidentifier() for part in record["module"].split('.'))
                    and type(record["name"]) is str and record["name"].isidentifier()
                    and record["path"] == record["module"].replace('.','/')+'.py'
                    and type(record["fields"]) is list and 1<=len(record["fields"])<=16
                    and all(type(f) is str and f.isidentifier() and not f.startswith('_')
                            for f in record["fields"])
                    and len(set(record["fields"]))==len(record["fields"]),
                    "Invalid finite native record source/fields")
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
            {k: v for k, v in spec.items() if k not in {"within", "producer_role", "batch"}},
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
        if "producer_role" in spec:
            require(spec["producer_role"] in ("parent", "worker"),
                    "Unsupported native producer role")
        if "batch" in spec:
            batch=spec["batch"]
            exact({k:v for k,v in batch.items() if k != "ordinal"},["local","max_items"],"native batch")
            require("ordinal" not in batch or batch["ordinal"] == "acquisition",
                    "Invalid native batch ordinal route")
            require(type(batch["local"]) is str and batch["local"].isidentifier()
                    and not batch["local"].startswith("__zr_")
                    and type(batch["max_items"]) is int and 1 <= batch["max_items"] <= 4096,
                    "Invalid native batch collection/bound")
        if "within" in spec:
            require(type(spec["within"]) is list and 1 <= len(spec["within"]) <= 8,
                    "Invalid native ancestor inventory")
            for ancestor in spec["within"]:
                exact(ancestor, ["header", "branch"], "native ancestor")
                require(type(ancestor["header"]) is str
                        and 0 < len(ancestor["header"]) <= 16384
                        and ancestor["branch"] in
                        ["body", "orelse", "finalbody"] +
                        ["handler:" + str(n) for n in range(16)],
                        "Invalid native ancestor header/branch")
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
            spec["position"]
            in [
                "before",
                "after",
                "try_success",
                "handler_entry",
                "before_return",
                "return_value",
            ],
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
        for field, value in spec["projection"].items():
            validate_projection(value)
            require('activation' not in value or (field in p['identity'] and p['identity'][field]=='int'),
                    'Activation belongs only to declared integer identity')
            for step in value.get("path",[]):
                if "stored" in step:
                    require(step["record"] in p.get("record_types",{})
                            and step["stored"] in p["record_types"][step["record"]]["fields"],
                            "Stored field lacks a native type declaration")
            require(not (set(value) & {"item","ordinal"}) or "batch" in spec,
                    "Native item/ordinal requires a declared batch")
            require(
                "return" not in value or spec["position"] == "return_value",
                "Native return projection requires a return-value site",
            )
            require(
                "context" not in value or field in p["identity"],
                "External context may supply identity metadata only",
            )
        if "batch" in spec:
            require(spec["batch"].get("ordinal") == "acquisition" or any(spec["projection"][k] == {"ordinal":True}
                        and p["identity"][k] == "int" for k in p["identity"]),
                    "Native batch requires an exact integer ordinal identity")
            require(spec["batch"].get("ordinal") != "acquisition"
                    or all("ordinal" not in value for value in spec["projection"].values()),
                    "Acquisition ordinal cannot also become a scientific projection")
            require(all("item" not in spec["projection"][k]
                        or (set(spec["projection"][k]) == {"item","path"}
                            and spec["projection"][k]["path"]
                            and "stored" in spec["projection"][k]["path"][0])
                        for k in p["identity"]),
                    "Native batch item identity requires declared stored native fields")
    require(
        not any("producer_role" in s for s in p["sites"].values())
        or all("producer_role" in s for s in p["sites"].values()),
        "Native producer roles must cover every site",
    )
    require(
        type(p["rules"]) is list and 1 <= len(p["rules"]) <= 64,
        "Invalid relationship inventory",
    )
    ids = set()
    for r in p["rules"]:
        exact(
            {k:v for k,v in r.items() if k not in {"inventory_policy","guard"}},
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
        if "guard" in r:
            guard=r["guard"]
            exact(guard,["kind","field","in"],"native rule guard")
            require(guard["kind"] in p["facts"]
                    and guard["field"] in p["facts"][guard["kind"]]
                    and type(guard["in"]) is list and 1 <= len(guard["in"]) <= 16
                    and all(typed(v,p["facts"][guard["kind"]][guard["field"]]) for v in guard["in"]),
                    "Invalid native status-membership guard")
            require(any(p["sites"][s]["kind"] == guard["kind"] for s in r["requires"]),
                    "Native guard requires its site qualification")
        if "inventory_policy" in r:
            require(r["inventory_policy"] == "complete_batch_membership"
                    and r["check"] == "C3",
                    "Unsupported native inventory policy")
            sources=[s for s in p["sites"].values() if s["kind"] == r["producer"]]
            require(sources and all("batch" in s for s in sources),
                    "Complete inventory policy requires native batch producers")
            require(all(set(r["keys"]) == {k for k in p["identity"]
                                            if not (set(s["projection"][k]) & {"ordinal","item"})}
                        for s in sources),
                    "Complete batch policy keys must match native batch group identity")
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
            {k:v for k,v in e.items() if k != "acquisition"},
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
        if p['sites'][e['site']].get('batch',{}).get('ordinal') == 'acquisition':
            require('acquisition' in e, 'Native batch acquisition identity missing')
            exact(e['acquisition'], ['batch','ordinal'], 'native acquisition identity')
            require(type(e['acquisition']['batch']) is int and e['acquisition']['batch'] > 0
                    and type(e['acquisition']['ordinal']) is int
                    and 0 <= e['acquisition']['ordinal'] < p['sites'][e['site']]['batch']['max_items'],
                    'Invalid native batch acquisition identity')
        else:
            require('acquisition' not in e, 'Undeclared acquisition identity')
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
    roles = {s["producer_role"] for s in p["sites"].values() if "producer_role" in s}
    exact(
        h,
        [
            "binding_sha256",
            "sites",
            "transport",
            "native_complete",
            "qualification_sha256",
        ] + (["producers"] if roles else []) +
        (["batch_journal"] if any("inventory_policy" in r for r in p["rules"]) else []),
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
    if roles:
        exact(h["producers"], roles, "native producer role mapping")
        require(all(v is None or (type(v) is int and v > 0
                                 and str(v) in h["transport"])
                    for v in h["producers"].values()), "Invalid native role/PID mapping")
        pids = [v for v in h["producers"].values() if v is not None]
        require(len(pids) == len(set(pids)), "Native producer roles cannot share a PID")
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
    if "producers" in health:
        require(all(health["producers"][p["sites"][e["site"]]["producer_role"]]
                    == e["producer"] for e in events),
                "Observation producer does not match its declared native role")
    batch_receipts=[]
    if "batch_journal" in health:
        from .batches import reconcile_batches
        reconciled=reconcile_batches(p,binding_sha,health["batch_journal"],
                                      source_sha=case["source_sha256"])
        by_id={e["id"]:e for e in events}
        require(all(by_id.get(e["id"]) == e for e in reconciled["events"]),
                "Retained native batch journal disagrees with semantic observations")
        batch_receipts=reconciled["batches"]
        require(all(str(v["producer"]) in health["transport"] for v in batch_receipts),
                "Native batch control lacks producer transport evidence")
        if "producers" in health:
            require(all(health["producers"][p["sites"][v["site"]]["producer_role"]]
                        == v["producer"] for v in batch_receipts),
                    "Native batch control producer mismatches its declared role")

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
        required_sites=r["requires"]
        if "producers" in health or "guard" in r:
            # Kind aliases cannot omit a native producer from an absence claim.
            required_sites=sorted(set(required_sites) | {s for s,spec in p["sites"].items()
                                                        if spec["kind"] in (r["producer"],r["consumer"],r.get("guard",{}).get("kind"))})
        coverage = all(health["sites"][s] is True for s in required_sites)
        for group in groups:
            ss, tt = source_groups.get(group, []), target_groups.get(group, [])
            evidence = [e["id"] for e in ss + tt]
            guards=[]
            if "guard" in r:
                guards=[e for e in monitor.by_kind[r["guard"]["kind"]]
                        if key(e["identity"],r["keys"]) == group]
                evidence += [e["id"] for e in guards]
            status, reasons = "CONFORMS", []
            duplicate = (
                len(tt) > 1
                or (r["check"] != "C3" and len(ss) > 1)
                or len({digest(e["identity"]) for e in ss}) != len(ss)
            )
            transport = bool(health["transport"]) and all(
                v is True for v in health["transport"].values()
            )
            if "producers" in health:
                required_roles = {p["sites"][s]["producer_role"] for s in required_sites}
                transport = all(health["producers"][role] is not None
                                and health["transport"][str(health["producers"][role])] is True
                                for role in required_roles)
            complete = health["native_complete"][r["id"]] is True
            closed_batch=False
            if "inventory_policy" in r:
                applicable=[v for v in batch_receipts
                            if p["sites"][v["site"]]["kind"] == r["producer"]
                            and key(v["identity"],r["keys"]) == group]
                closed_batch=(len(applicable)==1 and applicable[0]["complete"]
                              and set(applicable[0]["event_ids"]) == {e["id"] for e in ss}
                              and complete and transport)
            if "guard" in r and len(guards) != 1:
                status,reasons="INCONCLUSIVE",["missing_or_ambiguous_native_guard"]
            elif not coverage:
                status, reasons = "INCONCLUSIVE", ["unqualified_semantic_sites"]
            elif ("guard" in r and guards[0]["values"][r["guard"]["field"]]
                  not in r["guard"]["in"]):
                status,reasons="CONFORMS",["native_rule_guard_not_applicable"]
            elif duplicate:
                status, reasons = (
                    "INCONCLUSIVE",
                    ["ambiguous_or_duplicate_native_identity"],
                )
            elif not ss and not closed_batch:
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
                if {digest(e["identity"]) for e in ss} != inventory and value and not closed_batch:
                    status, reasons = "INCONCLUSIVE", ["aggregate_native_inventory_gap"]
                else:
                    if closed_batch:
                        value=value and {digest(e["identity"]) for e in ss} == inventory
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
                    required_sites=required_sites,
                    independently_orderable=False,
                )
            )
    return seal(
        dict(
            schema="zerorun-relationships/1",
            engine_version="1.1.0" if ("producers" in health or "batch_journal" in health
                                      or any("guard" in r for r in p["rules"])) else ENGINE_VERSION,
            policy_sha256=digest(p),
            binding_sha256=binding_sha,
            case_sha256=digest(case),
            qualification_sha256=health["qualification_sha256"],
            evidence_sha256=digest(events),
            records=rows,
            counts=dict(sorted(Counter(row["status"] for row in rows).items())),
        )
    )
