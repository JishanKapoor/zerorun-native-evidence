"""Execute callback/binding faults against a separately authored native reference."""

import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from declarative_support import SOURCE, profile, qualified_manifest
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.qualification import qualify

manifest, base_profile = qualified_manifest()
rows = []
for fault in ["normal", "missing_callback", "wrong_identity", "invalid_success_path"]:
    p = profile()
    if fault == "wrong_identity":
        p["sites"]["accept"]["projection"]["candidate"] = {
            "literal": "incorrect-candidate"
        }
    if fault == "invalid_success_path":
        p["sites"]["accept"]["anchor"] = "decision = False"
        p["sites"]["accept"]["position"] = "after"
    binding = generate_binding(p, {"native.py": SOURCE})
    events = []

    class Sink:
        def emit(self, value):
            events.append(copy.deepcopy(value))
            return True

    callback = recorder(p, binding, Sink(), os.getpid())

    def hook(site, state):
        if fault == "missing_callback" and site == "commit":
            return
        callback(site, state)

    scope = {"__zr_observe": hook}
    exec(compile(binding["transformed"]["native.py"], "native.py", "exec"), scope)
    native = scope["evaluate"]("run-1", "candidate-1", "base", 1, [True, False])
    assert native == ({0: True, 1: False}, 2, False)
    controls = copy.deepcopy(manifest["qualification"]["controls"])
    # Positive raw native references are pre-specified independently in the
    # retained fixture. Replace only observed runtime events, never references.
    controls = [c for c in controls if c["role"] == "positive"]
    for c in controls:
        c["observed"] = [e for e in events if e["site"] == c["site"]]
    if fault != "invalid_success_path":
        for site, inputs in [("accept", [False]), ("reject", [True])]:
            negative_events = []

            class NegativeSink:
                def emit(self, value):
                    negative_events.append(copy.deepcopy(value))
                    return True

            other = {"__zr_observe": recorder(p, binding, NegativeSink(), os.getpid())}
            exec(binding["transformed"]["native.py"], other)
            other["evaluate"]("run-1", "candidate-1", "base", 1, inputs)
            c = copy.deepcopy(
                next(
                    c
                    for c in manifest["qualification"]["controls"]
                    if c["id"] == site + "-negative"
                )
            )
            c["observed"] = [e for e in negative_events if e["site"] == site]
            controls.append(c)
    else:
        # The rejected disposition deliberately executes the wrongly bound
        # acceptance callback; positive reference mismatch must disqualify it.
        c = copy.deepcopy(
            next(
                c
                for c in manifest["qualification"]["controls"]
                if c["id"] == "reject-negative"
            )
        )
        c["observed"] = []
        controls.append(c)
    q = qualify(p, binding, controls)
    expected = {s: True for s in p["sites"]}
    if fault == "missing_callback":
        expected["commit"] = False
    if fault in ["wrong_identity", "invalid_success_path"]:
        expected["accept"] = False
    assert q["sites"] == expected, (fault, q["sites"])
    rows.append(
        dict(
            fault=fault,
            passed=True,
            native_result_preserved=True,
            expected_sites=expected,
            qualification=q,
            binding_sha256=binding["sha256"],
            policy_sha256=digest(p),
        )
    )
print(
    json.dumps(
        dict(
            passed=True,
            cases=len(rows),
            rows=rows,
            scope="Executed exposed callback faults, not unfamiliar primary native challenges",
        )
    )
)
