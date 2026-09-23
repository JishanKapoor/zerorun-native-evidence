"""Deterministic primitive-schema mutations; no native or primary candidate calls."""

import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from declarative_support import profile
from zerorun_harness.api import InvalidEvidence
from zerorun_harness.declarative import validate_profile


def paths(value, path=()):
    yield path
    if type(value) is dict:
        for k, v in value.items():
            yield from paths(v, path + (k,))
    elif type(value) is list:
        for k, v in enumerate(value):
            yield from paths(v, path + (k,))


values = [
    None,
    False,
    True,
    -1,
    0,
    1,
    1.5,
    "",
    "unrecognized",
    [],
    {},
    [None],
    {"opaque_checker": "python"},
    float("nan"),
]
original = profile()
counts = {"cases": 0, "refused": 0, "valid_finite_variants": 0}
for path in paths(original):
    for value in values:
        changed = copy.deepcopy(original)
        if path:
            node = changed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = copy.deepcopy(value)
        else:
            changed = copy.deepcopy(value)
        counts["cases"] += 1
        try:
            validate_profile(changed)
            counts["valid_finite_variants"] += 1
        except InvalidEvidence:
            counts["refused"] += 1
        except Exception as exc:
            print(
                json.dumps({"path": path, "exception": type(exc).__name__}), flush=True
            )
            raise
print(
    json.dumps(
        {
            "passed": True,
            "counts": counts,
            "native_calls": 0,
            "scope": "Malformed schema admission controls; valid primitive variants are not semantic qualification",
        }
    )
)
