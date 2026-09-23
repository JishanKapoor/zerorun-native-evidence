"""Executable refusal probes for exact exposed Inspect native source.

These are capability probes, not an installed native-domain profile and not
assertions that the release qualified Inspect's scoring pipeline.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

PIN = "f9837f6c577da1bf89223f0575d4cb218940a79f"
ROOT = Path(__file__).resolve().parent
SOURCES = {
    "run.py.txt": ("inspect_ai/_eval/task/run.py", "9f6a4f63e82ed9f4a697045472eec26f59f652d8fce7199eb4e6f5aa9ed3950b"),
    "results.py.txt": ("inspect_ai/_eval/task/results.py", "83d905c8fcc27c9965e85921cd3a5c16bcbff2a70d5e72ac9d74157a5d1221c9"),
    "metric.py.txt": ("inspect_ai/scorer/_metric.py", "07f6a0397ea287053da39184d208842d2c1b1331564ade45b9cc1de0f432ef29"),
}


def source(name):
    data = (ROOT / "sources" / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCES[name][1]:
        raise ValueError("Exposed Inspect source identity mismatch")
    return data.decode("utf-8")


def probe_profile(path, function, anchor, projection):
    identities = {"run": "str", "candidate": "str", "obligation": "int", "phase": "str", "attempt": "int"}
    identity_projections = {k: {"literal": v} for k, v in
                            {"run": "fit-probe", "candidate": "no-native-execution", "obligation": 0,
                             "phase": "source-admission-only", "attempt": 1}.items()}
    return {
        "api": "zerorun.extensions/1", "id": "inspect-admission-probe", "version": "0.0.0",
        "identity": identities, "facts": {"probe": {"raw": "int"}},
        "sites": {"site": {"kind": "probe", "path": path, "function": function,
                            "anchor": anchor, "position": "after", "multiplicity": 1,
                            "projection": {**identity_projections, "raw": projection},
                            "justification": "Source admission probe only; no native qualification or result claim"}},
        "rules": [{"id": "probe", "check": "C2", "producer": "probe", "consumer": "probe",
                   "keys": list(identities), "when": None, "source_field": "raw", "target_field": "raw",
                   "operator": "identity", "statuses": [], "target_mapping": None, "requires": ["site"],
                   "justification": "Never executed; a valid envelope used solely to probe source grammar refusal"}],
        "justification": "Finite structural feasibility probe, not a third domain extension",
    }


def async_commit_probe():
    text = source("run.py.txt")
    tree = ast.parse(text)
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "_task_run_sample_attempt")
    assignment = next(n for n in ast.walk(function) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                              and t.value.id == "results" for t in n.targets))
    path = SOURCES["run.py.txt"][0]
    # The literal is not an expected outcome: no callback is executed. It keeps
    # this probe focused on async source admission instead of object projection.
    return probe_profile(path, function.name, ast.unparse(assignment), {"literal": 0}), {path: text}


def synchronous_native_object_probe():
    text = source("results.py.txt")
    path = SOURCES["results.py.txt"][0]
    return probe_profile(path, "scorer_for_metrics", "sample_scores_with_values.append(sample_score)",
                         {"local": "sample_score", "path": [{"member": "score"}, {"member": "value"}]}), {path: text}
