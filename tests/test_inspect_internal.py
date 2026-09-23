"""Portable exact-source feasibility; real native execution has separate receipts."""
import ast
import importlib.util
from pathlib import Path

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import UnsupportedBinding, generate_binding
from zerorun_harness.projection import project, validate_projection
from zerorun_harness._telemetry_protocol import PrimitiveError

FOLDER = Path(__file__).resolve().parents[1] / "validation/inspect_internal"
spec = importlib.util.spec_from_file_location("inspect_internal_feasibility", FOLDER / "feasibility.py")
feasibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feasibility)


@pytest.mark.parametrize("name", list(feasibility.SOURCES))
def test_actual_inspect_source_identity(name):
    assert feasibility.source(name)


def test_actual_native_partial_commit_is_async_and_refused():
    p, sources = feasibility.async_commit_probe()
    tree = ast.parse(next(iter(sources.values())))
    assert any(isinstance(n, ast.AsyncFunctionDef) and n.name == "_task_run_sample_attempt" for n in tree.body)
    with pytest.raises(UnsupportedBinding):
        generate_binding(p, sources)


def test_actual_scorer_consumer_requires_unsupported_model_field_projection():
    p, sources = feasibility.synchronous_native_object_probe()
    tree = ast.parse(next(iter(sources.values())))
    assert any(isinstance(n, ast.FunctionDef) and n.name == "scorer_for_metrics" for n in tree.body)
    with pytest.raises(InvalidEvidence, match="Only native scalar value member"):
        generate_binding(p, sources)


def test_native_unscored_sentinel_is_not_silently_normalized_into_a_verdict():
    with pytest.raises(PrimitiveError, match="nonfinite"):
        project({"local": "score"}, {"score": float("nan")})


def test_generic_member_value_does_not_call_arbitrary_model_property():
    class UnknownModel:
        @property
        def value(self):
            raise AssertionError("Must not invoke a custom model field")
    validate_projection({"local": "score", "path": [{"member": "value"}]})
    with pytest.raises(PrimitiveError, match="Arbitrary native properties"):
        project({"local": "score", "path": [{"member": "value"}]}, {"score": UnknownModel()})
