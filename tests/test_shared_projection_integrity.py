"""Native wrapper instance plumbing must not dispatch user-supplied callbacks."""
import ctypes
import multiprocessing as mp

import pytest

from zerorun_harness._telemetry_protocol import PrimitiveError
from zerorun_harness.projection import project
from zerorun_harness.binding import generate_binding, recorder

from declarative_support import SOURCE, profile


def read(value, shape):
    path = [{"member": "value"}] if shape == "scalar" else [{"index": 0}]
    return project({"local": "native", "path": path}, {"native": value})


def make(shape, lock=None):
    options = {} if lock is None else {"lock": lock}
    return mp.Value("i", 7, **options) if shape == "scalar" else mp.Array("i", [7, 9], **options)


@pytest.mark.parametrize("shape", ["scalar", "array"])
def test_projection_rejects_overridden_get_obj_without_calling_it(shape):
    wrapper = make(shape)
    backing = wrapper.get_obj()
    called = []
    wrapper.get_obj = lambda: called.append("override") or backing
    with pytest.raises(PrimitiveError):
        read(wrapper, shape)
    assert called == []


@pytest.mark.parametrize("method", ["acquire", "release"])
def test_scalar_projection_rejects_overridden_lock_method_without_dispatch(method):
    wrapper = make("scalar")
    original = getattr(wrapper, method)
    called = []

    def replacement(*args, **kwargs):
        called.append(method)
        return original(*args, **kwargs)

    setattr(wrapper, method, replacement)
    with pytest.raises(PrimitiveError):
        read(wrapper, "scalar")
    assert called == []


@pytest.mark.parametrize("shape", ["scalar", "array"])
def test_projection_refuses_custom_lock_before_its_methods_execute(shape):
    called = []

    class CustomLock:
        def acquire(self, *args, **kwargs):
            called.append("acquire")
            return True

        def release(self):
            called.append("release")

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *args):
            self.release()

    wrapper = make(shape, CustomLock())
    called.clear()
    with pytest.raises(PrimitiveError):
        read(wrapper, shape)
    assert called == []


@pytest.mark.parametrize("shape", ["scalar", "array"])
@pytest.mark.parametrize("lock_factory", [mp.Lock, mp.RLock])
def test_standard_native_locks_remain_supported(shape, lock_factory):
    assert read(make(shape, lock_factory()), shape) == 7


@pytest.mark.parametrize("synchronized", [False, True])
def test_projection_rejects_mutated_cached_native_array_class(monkeypatch, synchronized):
    array_type = ctypes.c_int * 2
    native = mp.Array("i", [7, 9]) if synchronized else array_type(7, 9)
    called = []
    monkeypatch.setattr(array_type, "__getitem__", lambda self, index: called.append(index) or 7, raising=False)
    with pytest.raises(PrimitiveError):
        read(native, "array")
    assert called == []


def test_missing_native_lock_backing_is_a_projection_refusal():
    native = make("scalar")
    del native.get_lock()._semlock
    assert native.value == 7  # The native bound acquire/release methods still work.
    with pytest.raises(PrimitiveError):
        read(native, "scalar")


@pytest.mark.parametrize("synchronized", [False, True])
def test_standard_scalar_class_definition_metadata(monkeypatch, synchronized):
    native = mp.Value("i", 7) if synchronized else ctypes.c_int(7)
    monkeypatch.setattr(ctypes.c_int, "__firstlineno__", 191, raising=False)
    monkeypatch.setattr(ctypes.c_int, "__static_attributes__", (), raising=False)
    assert read(native, "scalar") == 7


@pytest.mark.parametrize("name,value", [
    ("__firstlineno__", True), ("__firstlineno__", 0),
    ("__firstlineno__", "191"), ("__static_attributes__", []),
    ("__static_attributes__", ("value",)), ("unexpected_hook", None),
])
def test_altered_scalar_metadata_is_refused(monkeypatch, name, value):
    native = ctypes.c_int(7)
    monkeypatch.setattr(ctypes.c_int, name, value, raising=False)
    with pytest.raises(PrimitiveError):
        read(native, "scalar")


@pytest.mark.parametrize("name", ["__firstlineno__", "__static_attributes__"])
def test_scalar_metadata_never_dispatches_candidate_protocols(monkeypatch, name):
    called = []

    class Candidate:
        def __eq__(self, other):
            called.append("eq")
            return True

        def __gt__(self, other):
            called.append("gt")
            return True

        def __len__(self):
            called.append("len")
            return 0

    native = ctypes.c_int(7)
    monkeypatch.setattr(ctypes.c_int, name, Candidate(), raising=False)
    with pytest.raises(PrimitiveError):
        read(native, "scalar")
    assert called == []


@pytest.mark.parametrize("mutation", ["projection", "binding-digest", "fact-schema"])
def test_recorder_freezes_verified_declarations_against_later_caller_mutation(mutation):
    policy = profile()
    binding = generate_binding(policy, {"native.py": SOURCE})
    original_sha = binding["sha256"]
    events = []

    class Emitter:
        def emit(self, event):
            events.append(event)

    observe = recorder(policy, binding, Emitter(), 1)
    if mutation == "projection":
        policy["sites"]["commit"]["projection"]["stored"] = {"literal": False}
    elif mutation == "binding-digest":
        binding["sha256"] = "f" * 64
    else:
        policy["facts"]["commit"] = {"missing": "str"}
    observe("commit", {"run": "r", "candidate": "c", "phase": "base", "attempt": 1, "obligation": 0, "stored": True})
    assert len(events) == 1
    assert events[0]["values"] == {"stored": True}
    assert events[0]["binding_sha256"] == original_sha
