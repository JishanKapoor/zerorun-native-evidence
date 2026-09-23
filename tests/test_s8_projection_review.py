"""Independent S8 boundary review: a refusal must not run candidate hooks."""

import ctypes
import multiprocessing as mp

import pytest

from zerorun_harness._telemetry_protocol import PrimitiveError, primitives
from zerorun_harness.api import InvalidEvidence, canonical
from zerorun_harness.projection import project, read_index, validate_projection


def hostile(called, *, equal=False, hash_trap=False):
    class Meta(type):
        def __eq__(cls, other):
            called.append("metaclass equality")
            return equal

        def __hash__(cls):
            called.append("metaclass hash")
            if hash_trap:
                raise AssertionError("candidate metaclass hash executed")
            return 123

    class Candidate(metaclass=Meta):
        def __len__(self):
            called.append("candidate length")
            return 1

        def __iter__(self):
            called.append("candidate iterator")
            return iter(["a"])

        def __contains__(self, needle):
            called.append("candidate membership")
            return True

        def __getitem__(self, index):
            called.append("candidate index")
            return "a"

    return Candidate()


@pytest.mark.parametrize("equal", [False, True])
@pytest.mark.parametrize("operation", ["size", "contains", "index", "member", "plain", "primitive"])
def test_hostile_metaclass_refusal_is_nonexecuting(equal, operation):
    called = []
    value = hostile(called, equal=equal)
    specs = {
        "size": {"size": True},
        "contains": {"contains": {"literal": "a"}},
        "index": {"path": [{"index": 0}]},
        "member": {"path": [{"member": "value"}]},
        "plain": {},
    }
    with pytest.raises(PrimitiveError):
        if operation == "primitive":
            primitives(value)
        else:
            project({"local": "x", **specs[operation]}, {"x": value})
    assert called == []


@pytest.mark.parametrize("place", ["needle", "list-item", "dict-key", "index", "index-map-key"])
def test_hostile_selector_and_member_types_are_not_compared(place):
    called = []
    value = hostile(called, equal=True)
    with pytest.raises(PrimitiveError):
        if place == "needle":
            project({"local": "x", "contains": {"local": "n"}}, {"x": ["a"], "n": value})
        elif place == "list-item":
            project({"local": "x", "contains": {"literal": "a"}}, {"x": [value]})
        elif place == "dict-key":
            project({"local": "x", "contains": {"literal": "a"}}, {"x": {value: 1}})
        elif place == "index":
            read_index({"a": 1}, value)
        else:
            read_index({value: 1}, "a")
    assert called == []


def test_sorted_snapshot_does_not_hash_candidate_types():
    called = []
    value = hostile(called, hash_trap=True)
    with pytest.raises(PrimitiveError):
        project({"local": "x", "encoding": "sorted_json"}, {"x": {value}})
    assert called == []


def test_size_refuses_forged_lock_without_metaclass_dispatch():
    called = []
    array = mp.Array("i", [1, 2])
    lock = hostile(called, equal=True)
    # Even copying the real semaphore into a forged lock cannot admit its type.
    lock._semlock = array.get_lock()._semlock
    array._lock = lock
    with pytest.raises(PrimitiveError):
        project({"local": "x", "size": True}, {"x": array})
    assert called == []


@pytest.mark.parametrize("synchronized", [False, True])
@pytest.mark.parametrize("mutation", ["length-hook", "wrong-length", "wrong-element"])
def test_size_refuses_mutated_native_array_class(monkeypatch, synchronized, mutation):
    # Use a distinct length to avoid other fixture types in ctypes' cache.
    array_type = ctypes.c_int * 29
    value = mp.Array("i", 29) if synchronized else array_type()
    called = []
    if mutation == "length-hook":
        monkeypatch.setattr(array_type, "__len__", lambda self: called.append("length") or 7, raising=False)
    elif mutation == "wrong-length":
        monkeypatch.setattr(array_type, "_length_", 30)
    else:
        monkeypatch.setattr(array_type, "_type_", ctypes.c_double)
    with pytest.raises(PrimitiveError):
        project({"local": "x", "size": True}, {"x": value})
    assert called == []


@pytest.mark.parametrize("mutation", ["extra-method", "wrong-backing", "acquire", "release", "missing-semaphore"])
def test_size_refuses_mutated_shared_array_plumbing(mutation):
    value = mp.Array("i", [1, 2])
    called = []
    if mutation == "extra-method":
        value.get_obj = lambda: called.append("get_obj") or value._obj
    elif mutation == "wrong-backing":
        value._obj = hostile(called)
    elif mutation in ("acquire", "release"):
        setattr(value, mutation, lambda *args: called.append(mutation))
    else:
        del value.get_lock()._semlock
    with pytest.raises(PrimitiveError):
        project({"local": "x", "size": True}, {"x": value})
    assert called == []


def test_allowed_collection_limits_are_inclusive():
    membership = {"local": "x", "contains": {"literal": 4095}}
    assert project(membership, {"x": list(range(4096))}) is True
    with pytest.raises(PrimitiveError):
        project(membership, {"x": list(range(4097))})
    snapshot = {"local": "x", "encoding": "sorted_json"}
    assert project(snapshot, {"x": set(range(64))}).endswith("62,63]")
    with pytest.raises(PrimitiveError):
        project(snapshot, {"x": set(range(65))})


def test_size_and_membership_do_not_examine_unneeded_values():
    called = []
    value = hostile(called)
    assert project({"local": "x", "size": True}, {"x": [value]}) == 1
    assert project({"local": "x", "contains": {"literal": "a"}}, {"x": {"a": value}}) is True
    assert called == []


@pytest.mark.parametrize("needle", [True, 1.0, 2**129, "x" * 1025, "\ud800"])
def test_dynamic_membership_selector_limits(needle):
    with pytest.raises(PrimitiveError):
        project({"local": "x", "contains": {"local": "n"}}, {"x": ["a"], "n": needle})


@pytest.mark.parametrize("needle", [True, 1.0, 2**129, "x" * 1025, "\ud800"])
def test_declared_membership_selector_limits(needle):
    with pytest.raises(InvalidEvidence):
        validate_projection({"local": "x", "contains": {"literal": needle}})


@pytest.mark.parametrize("value", [{False}, {1.0}, {"a", 1}, {"\ud800"}, {2**129}])
def test_sorted_snapshot_refuses_noncanonical_element_domain(value):
    with pytest.raises(PrimitiveError):
        project({"local": "x", "encoding": "sorted_json"}, {"x": value})


def test_canonical_unicode_snapshot_is_deterministic():
    assert project({"local": "x", "encoding": "sorted_json"}, {"x": {"é", "a", "\n"}}) == '["\\n","a","é"]'


def test_membership_checks_all_keys_before_short_circuit():
    called = []
    value = hostile(called)
    with pytest.raises(PrimitiveError):
        project({"local": "x", "contains": {"literal": "a"}}, {"x": ["a", value]})
    assert called == []


@pytest.mark.parametrize("synchronized", [False, True])
@pytest.mark.parametrize("mutation", ["descriptor", "getattribute"])
def test_mutated_exact_ctypes_scalar_descriptor_is_not_executed(monkeypatch, synchronized, mutation):
    value = mp.Value("i", 7) if synchronized else ctypes.c_int(7)
    called = []
    if mutation == "descriptor":
        monkeypatch.setattr(ctypes.c_int, "value", property(lambda self: called.append("property") or 91))
    else:
        original = ctypes.c_int.__getattribute__

        def getattribute(self, name):
            called.append(name)
            return original(self, name)

        monkeypatch.setattr(ctypes.c_int, "__getattribute__", getattribute)
    with pytest.raises(PrimitiveError):
        project({"local": "x", "path": [{"member": "value"}]}, {"x": value})
    assert called == []


@pytest.mark.parametrize("equal", [False, True])
def test_canonical_json_boundary_refuses_metaclass_objects_without_dispatch(equal):
    called = []
    value = hostile(called, equal=equal)
    with pytest.raises(InvalidEvidence):
        canonical({"payload": value})
    assert called == []
