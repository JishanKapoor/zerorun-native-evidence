"""Exposed native fixture; expected policy is independently specified in tests."""

import copy
import os
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding, recorder

SOURCE = """def evaluate(run, candidate, phase, attempt, inputs, omit=False, corrupt=False):
    details = {}
    progress = 0
    for obligation, value in enumerate(inputs):
        if value is None:
            continue
        try:
            assert value
        except AssertionError:
            decision = False
        else:
            decision = True
        if omit:
            continue
        stored = not decision if corrupt else decision
        details[obligation] = stored
        progress += 1
        serialized = int(stored)
    aggregate = all(details.values())
    return details, progress, aggregate
"""
TRY = """try:
    assert value
except AssertionError:
    decision = False
else:
    decision = True
"""


def profile():
    identity = {
        "run": "str",
        "candidate": "str",
        "obligation": "int",
        "phase": "str",
        "attempt": "int",
    }
    facts = {
        "decision": {"accepted": "bool", "disposition": "str"},
        "commit": {"stored": "bool"},
        "serialized": {"flag": "int"},
        "aggregate": {"accepted": "bool"},
    }

    def site(kind, anchor, position, values):
        return dict(
            kind=kind,
            path="native.py",
            function="evaluate",
            anchor=anchor,
            position=position,
            multiplicity=1,
            projection={**{k: {"local": k} for k in identity}, **values},
            justification="Exposed native fixture operations; no primary historical credit",
        )

    sites = {
        "accept": site(
            "decision",
            TRY,
            "try_success",
            {"accepted": {"literal": True}, "disposition": {"literal": "accepted"}},
        ),
        "reject": site(
            "decision",
            TRY,
            "handler_entry",
            {"accepted": {"literal": False}, "disposition": {"literal": "rejected"}},
        ),
        "commit": site(
            "commit",
            "details[obligation] = stored",
            "after",
            {"stored": {"local": "stored"}},
        ),
        "serialize": site(
            "serialized",
            "serialized = int(stored)",
            "after",
            {"flag": {"local": "serialized"}},
        ),
        "aggregate": site(
            "aggregate",
            "aggregate = all(details.values())",
            "after",
            {"accepted": {"local": "aggregate"}},
        ),
    }

    def rule(ident, check, a, b, source, target, op, requires):
        return dict(
            id=ident,
            check=check,
            producer=a,
            consumer=b,
            keys=[k for k in identity if check != "C3" or k != "obligation"],
            when=None,
            source_field=source,
            target_field=target,
            operator=op,
            statuses=[],
            target_mapping=None,
            requires=requires,
            justification="Native fixture disposition, store, typed serialization and conjunction",
        )

    rules = [
        rule(
            "commit-required",
            "C1",
            "decision",
            "commit",
            None,
            None,
            "exists",
            ["accept", "reject", "commit"],
        ),
        rule(
            "decision-preserved",
            "C2",
            "decision",
            "commit",
            "accepted",
            "stored",
            "identity",
            ["accept", "reject", "commit"],
        ),
        rule(
            "serialization-preserved",
            "C2",
            "commit",
            "serialized",
            "stored",
            "flag",
            "bool_to_int",
            ["commit", "serialize"],
        ),
        rule(
            "aggregate-derived",
            "C3",
            "commit",
            "aggregate",
            "stored",
            "accepted",
            "all",
            ["commit", "aggregate"],
        ),
    ]
    rules[0]["when"] = {"field": "disposition", "in": ["accepted", "rejected"]}
    return dict(
        api="zerorun.extensions/1",
        id="exposed-native",
        version="1.0.0",
        identity=identity,
        facts=facts,
        sites=sites,
        rules=rules,
        justification="Development qualification fixture, not an independent extension",
    )


def execute(inputs=(True, False), *, omit=False, corrupt=False):
    p = profile()
    binding = generate_binding(p, {"native.py": SOURCE})
    events = []

    class Sink:
        def emit(self, value):
            events.append(copy.deepcopy(value))
            return True

    scope = {"__zr_observe": recorder(p, binding, Sink(), os.getpid())}
    exec(compile(binding["transformed"]["native.py"], "native.py", "exec"), scope)
    outcome = scope["evaluate"](
        "run-1", "candidate-1", "base", 1, inputs, omit, corrupt
    )
    inventory = [
        dict(
            run="run-1", candidate="candidate-1", obligation=i, phase="base", attempt=1
        )
        for i in range(len(inputs))
    ]
    case = dict(
        id="development",
        version="1",
        inventory=inventory,
        source_sha256=digest(binding["original_sources"]),
        input_sha256=digest(list(inputs)),
    )
    health = dict(
        binding_sha256=binding["sha256"],
        sites={s: True for s in p["sites"]},
        transport={str(os.getpid()): True},
        native_complete={r["id"]: True for r in p["rules"]},
        qualification_sha256="1" * 64,
    )
    return p, binding, case, events, health, outcome


def qualified_manifest():
    """Reference observations explicitly authored for the exposed fixture only."""
    from zerorun_harness.qualification import qualify

    p, binding, case, events, health, _ = execute()
    # Independent primitive specification: no output of the observer or mapper
    # is used to construct the expected native reference values below.
    identity = lambda i: dict(
        run="run-1", candidate="candidate-1", obligation=i, phase="base", attempt=1
    )
    native_expected = {
        "accept": [
            dict(
                identity=identity(0),
                values={"accepted": True, "disposition": "accepted"},
            )
        ],
        "reject": [
            dict(
                identity=identity(1),
                values={"accepted": False, "disposition": "rejected"},
            )
        ],
        "commit": [
            dict(identity=identity(0), values={"stored": True}),
            dict(identity=identity(1), values={"stored": False}),
        ],
        "serialize": [
            dict(identity=identity(0), values={"flag": 1}),
            dict(identity=identity(1), values={"flag": 0}),
        ],
        "aggregate": [dict(identity=identity(1), values={"accepted": False})],
    }
    controls = []

    def control(site, role, expected, observed):
        return dict(
            id=site + "-" + role,
            site=site,
            role=role,
            reference=dict(
                source_sha256=digest(
                    "independent authored specification in declarative_support.py"
                ),
                recipe_sha256=digest(
                    {
                        "fixture": "assertion/store/serialization/conjunction",
                        "site": site,
                        "role": role,
                    }
                ),
                native_source_sha256=digest(binding["original_sources"]),
                output_sha256=digest(expected),
                framework_semantics_imported=False,
                facts=expected,
            ),
            observed=observed,
        )

    for site, expected in native_expected.items():
        controls.append(
            control(
                site, "positive", expected, [e for e in events if e["site"] == site]
            )
        )
    rejected = execute([False])[3]
    accepted = execute([True])[3]
    controls.append(
        control(
            "accept", "negative", [], [e for e in rejected if e["site"] == "accept"]
        )
    )
    controls.append(
        control(
            "reject", "negative", [], [e for e in accepted if e["site"] == "reject"]
        )
    )
    certificate = qualify(p, binding, controls)
    health.update(
        sites=copy.deepcopy(certificate["sites"]),
        qualification_sha256=certificate["sha256"],
    )
    return dict(
        schema="zerorun-extension-manifest/1",
        extension={"id": p["id"], "version": p["version"], "sha256": digest(p)},
        binding=binding,
        case=case,
        observations=events,
        health=health,
        qualification=certificate,
    ), p
