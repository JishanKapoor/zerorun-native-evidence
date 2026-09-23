"""Independent lifecycle control-flow and sealed-input regression review."""

import builtins
import contextlib
import copy
import hashlib

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding
from zerorun_harness.declarative import seal
from zerorun_harness.lifecycle_binding import (
    generate_lifecycle_binding,
    validate_lifecycle_binding,
)
from test_native_projection import one_site


def base(source):
    profile = one_site("outer", "marker = 1", "after", {"local": "marker"})
    return generate_binding(profile, {"native.py": source})


def wrap(source, specs=None):
    binding = base(source)
    if specs is None:
        specs = [{"function": "outer", "role": "worker"}]
    envelope = generate_lifecycle_binding(binding, {"native.py": specs})
    validate_lifecycle_binding(binding, envelope)
    return envelope["transformed"]["native.py"]


def executor(source, log):
    @contextlib.contextmanager
    def lifecycle(role, function, state):
        log.append(("enter", function))
        try:
            yield
        except BaseException as exc:
            log.append(("exit-error", function, exc))
            raise
        else:
            log.append(("exit-normal", function))

    namespace = {"__zr_lifecycle": lifecycle, "__zr_observe": lambda *args: None}
    exec(compile(source, "native.py", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("outer_first", [False, True])
def test_nested_envelopes_resolve_from_original_lexical_tree(outer_first):
    source = """def outer(value):
    marker = 1
    def inner():
        return value
    return inner()
"""
    specs = [{"function": "outer", "role": "parent"}, {"function": "outer.inner", "role": "worker"}]
    if not outer_first:
        specs.reverse()
    log = []
    value = object()
    scope = executor(wrap(source, specs), log)
    assert scope["outer"](value) is value
    assert log == [("enter", "outer"), ("enter", "outer.inner"), ("exit-normal", "outer.inner"), ("exit-normal", "outer")]


def test_nonlocal_closure_and_native_finally_keep_original_scope():
    source = """def outer(value, log):
    marker = 1
    def inner():
        nonlocal value
        try:
            return value
        finally:
            value = 'changed'
            log.append('native-cleanup')
    result = inner()
    return result, value
"""
    log = []
    value = object()
    specs = [{"function": "outer.inner", "role": "worker"}, {"function": "outer", "role": "parent"}]
    scope = executor(wrap(source, specs), log)
    result, state = scope["outer"](value, log)
    assert result is value and state == "changed"
    assert log == [("enter", "outer"), ("enter", "outer.inner"), "native-cleanup", ("exit-normal", "outer.inner"), ("exit-normal", "outer")]


@pytest.mark.parametrize("exception", [KeyboardInterrupt("stop"), SystemExit(5), GeneratorExit(), builtins.ExceptionGroup("group", [ValueError("leaf")])])
def test_base_exception_identity_and_cleanup_precede_lifecycle_exit(exception):
    source = """def outer(error, log):
    marker = 1
    try:
        raise error
    finally:
        log.append('native-cleanup')
"""
    log = []
    scope = executor(wrap(source), log)
    with pytest.raises(type(exception)) as caught:
        scope["outer"](exception, log)
    assert caught.value is exception
    assert log == [("enter", "outer"), "native-cleanup", ("exit-error", "outer", exception)]


def test_native_context_exit_changes_result_before_lifecycle_exit():
    source = """def outer(manager, log):
    marker = 1
    with manager:
        raise ValueError('suppressed natively')
    log.append('after-native-with')
    return 9
"""
    log = []

    class Manager:
        def __enter__(self):
            log.append("native-enter")

        def __exit__(self, *args):
            log.append("native-suppress")
            return True

    scope = executor(wrap(source), log)
    assert scope["outer"](Manager(), log) == 9
    assert log == [("enter", "outer"), "native-enter", "native-suppress", "after-native-with", ("exit-normal", "outer")]


def test_native_finally_exception_is_reported_instead_of_displaced_error():
    source = """def outer(first, second):
    marker = 1
    try:
        raise first
    finally:
        raise second
"""
    log = []
    first, second = ValueError("first"), RuntimeError("second")
    scope = executor(wrap(source), log)
    with pytest.raises(RuntimeError) as caught:
        scope["outer"](first, second)
    assert caught.value is second and second.__context__ is first
    assert log[-1] == ("exit-error", "outer", second)


@pytest.mark.parametrize("source", [
    "def outer(__zr_lifecycle):\n marker = 1\n",
    "__zr_lifecycle = None\ndef outer():\n marker = 1\n",
    "def outer():\n marker = 1\n return __zr_lifecycle\n",
    "def outer():\n marker = 1\n try: pass\n except Exception as __zr_lifecycle: pass\n",
    "def outer(value):\n marker = 1\n match value:\n  case {'a': __zr_lifecycle}: pass\n",
    "import contextlib as __zr_lifecycle\ndef outer():\n marker = 1\n",
])
def test_lifecycle_hook_collision_refuses_all_static_bindings(source):
    binding = base(source)
    with pytest.raises(InvalidEvidence):
        generate_lifecycle_binding(binding, {"native.py": [{"function": "outer", "role": "worker"}]})


@pytest.mark.parametrize("target", [
    "async def target():\n return 1\n",
    "def target():\n yield 1\n",
    "@deco\ndef target():\n return 1\n",
])
def test_unqualified_lifecycle_function_forms_refuse(target):
    binding = base("def outer():\n marker = 1\n" + target)
    with pytest.raises(InvalidEvidence):
        generate_lifecycle_binding(binding, {"native.py": [{"function": "target", "role": "worker"}]})


@pytest.mark.parametrize("declarations", [
    None, {}, [], {"missing.py": [{"function": "outer", "role": "worker"}]},
    {"native.py": []}, {"native.py": [None]},
    {"native.py": [{"function": "outer", "role": "unknown"}]},
    {"native.py": [{"function": "outer", "role": "worker", "extra": 1}]},
    {"native.py": [{"function": "outer", "role": "worker"}] * 2},
])
def test_malformed_lifecycle_declarations_are_explicit_refusals(declarations):
    binding = base("def outer():\n marker = 1\n")
    with pytest.raises(InvalidEvidence):
        generate_lifecycle_binding(binding, declarations)


@pytest.mark.parametrize("source", ["def outer(:\n", "def outer():\n    continue\n"])
def test_coherently_sealed_malformed_source_is_explicit_refusal(source):
    binding = base("def outer():\n marker = 1\n")
    body = {k: copy.deepcopy(v) for k, v in binding.items() if k != "sha256"}
    body["transformed"]["native.py"] = source
    body["transformed_sources"]["native.py"] = hashlib.sha256(source.encode()).hexdigest()
    with pytest.raises(InvalidEvidence):
        generate_lifecycle_binding(seal(body), {"native.py": [{"function": "outer", "role": "worker"}]})


def test_lifecycle_validation_detects_resealed_output_tampering():
    binding = base("def outer():\n marker = 1\n return 1\n")
    envelope = generate_lifecycle_binding(binding, {"native.py": [{"function": "outer", "role": "worker"}]})
    body = {k: copy.deepcopy(v) for k, v in envelope.items() if k != "sha256"}
    body["transformed"]["native.py"] += "unexpected = True\n"
    body["transformed_sources"]["native.py"] = hashlib.sha256(body["transformed"]["native.py"].encode()).hexdigest()
    with pytest.raises(InvalidEvidence):
        validate_lifecycle_binding(binding, seal(body))
