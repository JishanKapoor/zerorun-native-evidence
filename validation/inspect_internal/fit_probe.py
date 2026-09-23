"""Run common-grammar refusal probes against real installed Inspect values."""
from __future__ import annotations

import json
from feasibility import async_commit_probe, synchronous_native_object_probe
from inspect_ai.scorer import Score
from zerorun_harness.binding import generate_binding
from zerorun_harness.projection import project


def main():
    rows = []
    for name, factory in [("native_async_commit", async_commit_probe),
                          ("native_model_field_path", synchronous_native_object_probe)]:
        p, sources = factory()
        try:
            generate_binding(p, sources)
            rows.append({"case": name, "refused": False})
        except Exception as exc:
            rows.append({"case": name, "refused": True, "type": type(exc).__name__, "message": str(exc)})
    for name, spec, value in [
        ("native_score_object", {"local": "score", "path": [{"member": "value"}]}, Score(value=1)),
        ("native_unscored_value", {"local": "score"}, Score.unscored().value),
    ]:
        try:
            project(spec, {"score": value})
            rows.append({"case": name, "refused": False})
        except Exception as exc:
            rows.append({"case": name, "refused": True, "type": type(exc).__name__, "message": str(exc)})
    payload = {"schema": "inspect-grammar-feasibility/1", "source_revision": "f9837f6c577da1bf89223f0575d4cb218940a79f",
               "fits_unchanged_current_common_grammar": False, "observations": rows,
               "scope": "Expected supported-boundary refusals; not four successfully qualified native relationships"}
    print(json.dumps(payload, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
