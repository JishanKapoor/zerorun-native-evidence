"""Independent adversarial controls for opt-in stored native records."""

import copy
import math
from types import ModuleType

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding
from zerorun_harness.projection import project
from zerorun_harness.records import register_records
from zerorun_harness._telemetry_protocol import PrimitiveError
from test_native_records import MODEL, SPEC, prepared


@pytest.mark.parametrize("new_base_has_property", [False, True])
def test_changed_registered_mro_is_refused_without_property_dispatch(
    monkeypatch, new_base_has_property
):
    source = '''class Base:
    __slots__ = ()
class Other:
    __slots__ = ()
class Score(Base):
    value: float
    def __init__(self, value): self.value = value
'''
    _, _, module, registry = prepared(monkeypatch, source)
    calls = []
    if new_base_has_property:
        module.Other.value = property(lambda self: calls.append("property") or 99)
    score = module.Score(7)
    module.Score.__bases__ = (module.Other,)
    with pytest.raises(PrimitiveError):
        project(SPEC, {"score": score}, records=registry)
    assert calls == []


def test_changed_inherited_dictionary_owner_has_typed_refusal(monkeypatch):
    source = '''class Base: pass
class Other: pass
class Score(Base):
    value: float
    def __init__(self, value): self.value = value
'''
    _, _, module, registry = prepared(monkeypatch, source)
    score = module.Score(7)
    module.Score.__bases__ = (module.Other,)
    with pytest.raises(PrimitiveError):
        project(SPEC, {"score": score}, records=registry)


def test_registered_hostile_metaclass_never_receives_dispatch(monkeypatch):
    source = '''calls = []
class Meta(type):
    def __getattribute__(cls, key):
        calls.append(('getattribute', key))
        return super().__getattribute__(key)
    def __eq__(cls, other):
        calls.append(('eq',))
        return False
    def __hash__(cls):
        calls.append(('hash',))
        return 1
class Score(metaclass=Meta):
    value: float
    def __init__(self, value): self.value = value
'''
    p, b, module, _ = prepared(monkeypatch, source)
    score = module.Score(7)
    module.calls.clear()
    registry = register_records(p, b, {"score": module.Score})
    assert project(SPEC, {"score": score}, records=registry) == "7"
    assert module.calls == []


@pytest.mark.parametrize("mutation", ["mapping_subclass", "key_subclass", "non_string_key"])
def test_instance_dictionary_requires_exact_storage_without_hooks(monkeypatch, mutation):
    _, _, module, registry = prepared(monkeypatch)
    calls = []

    class Mapping(dict):
        def __iter__(self):
            calls.append("iter")
            return super().__iter__()

        def __getitem__(self, key):
            calls.append("get")
            return super().__getitem__(key)

    class Key(str):
        def __eq__(self, other):
            calls.append("eq")
            return super().__eq__(other)

        __hash__ = str.__hash__

    score = module.Score(7)
    if mutation == "mapping_subclass":
        score.__dict__ = Mapping(value=7)
    elif mutation == "key_subclass":
        score.__dict__ = {Key("value"): 7}
    else:
        score.__dict__ = {"value": 7, 1: 8}
    calls.clear()
    with pytest.raises(PrimitiveError):
        project(SPEC, {"score": score}, records=registry)
    assert calls == []


def test_caller_class_inventory_and_declared_fields_cannot_retarget_registry(monkeypatch):
    p, b, module, _ = prepared(monkeypatch)
    classes = {"score": module.Score}
    registry = register_records(p, b, classes)
    classes["score"] = object
    p["record_types"]["score"]["fields"][:] = ["other"]
    value = module.Score(7)
    value.other = 99
    assert registry.read(value, "score", "value") == 7
    with pytest.raises(PrimitiveError):
        registry.read(value, "score", "other")


@pytest.mark.parametrize("damage", ["module", "name", "loaded_identity", "module_subclass"])
def test_runtime_registration_requires_exact_loaded_declared_identity(monkeypatch, damage):
    p, b, module, _ = prepared(monkeypatch)
    cls = module.Score
    if damage == "module":
        cls.__module__ = "wrong"
    elif damage == "name":
        cls.__qualname__ = "Wrong"
    elif damage == "loaded_identity":
        module.Score = object
    else:
        class CustomModule(ModuleType):
            def __getattribute__(self, key):
                raise AssertionError("module hook must not execute")
        import sys
        monkeypatch.setitem(sys.modules, "native_model", CustomModule("native_model"))
    with pytest.raises(InvalidEvidence):
        register_records(p, b, {"score": cls})


@pytest.mark.parametrize("damage", ["missing_source", "wrong_class", "unannotated", "duplicate_class"])
def test_original_source_declaration_is_required(monkeypatch, damage):
    p, b, _, _ = prepared(monkeypatch)
    sources = copy.deepcopy(b["original"])
    if damage == "missing_source":
        del sources["native_model.py"]
    elif damage == "wrong_class":
        sources["native_model.py"] = MODEL.replace("Score", "Other")
    elif damage == "unannotated":
        sources["native_model.py"] = MODEL.replace("    value: float\n", "")
    else:
        sources["native_model.py"] = MODEL + MODEL
    with pytest.raises(InvalidEvidence):
        generate_binding(p, sources, grammar_version="1.3.0")


@pytest.mark.parametrize("value", [2**128, -(2**128)])
def test_number_tokens_retain_wire_integer_bound(value):
    with pytest.raises(PrimitiveError):
        project({"local": "x", "encoding": "number_json"}, {"x": value})


@pytest.mark.parametrize("base", [int, float])
def test_number_tokens_refuse_numeric_subclass_without_coercion(base):
    calls = []

    class Native(base):
        def __float__(self):
            calls.append("float")
            return 99.0

        def __int__(self):
            calls.append("int")
            return 99

        def __repr__(self):
            calls.append("repr")
            return "99"

    with pytest.raises(PrimitiveError):
        project({"local": "x", "encoding": "number_json"}, {"x": Native(7)})
    assert calls == []


def test_number_tokens_distinguish_signed_zero_nonfinite_and_missing(monkeypatch):
    _, _, module, registry = prepared(monkeypatch)
    expected = [(0.0, "0.0"), (-0.0, "-0.0"), (math.nan, "NaN"),
                (math.inf, "Infinity"), (-math.inf, "-Infinity"),
                (2**128 - 1, str(2**128 - 1))]
    assert [project(SPEC, {"score": module.Score(v)}, records=registry)
            for v, _ in expected] == [token for _, token in expected]
    value = module.Score(7)
    del value.value
    with pytest.raises(PrimitiveError):
        project(SPEC, {"score": value}, records=registry)


def test_changed_ancestor_namespace_refused_without_descriptor_evaluation(monkeypatch):
    source = '''class Base: pass
class Score(Base):
    value: float
    def __init__(self, value): self.value = value
'''
    _, _, module, registry = prepared(monkeypatch, source)
    value = module.Score(7)
    calls = []
    module.Base.value = property(lambda self: calls.append("property") or 99)
    with pytest.raises(PrimitiveError):
        project(SPEC, {"score": value}, records=registry)
    assert calls == []
