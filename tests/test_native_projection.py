# SPDX-License-Identifier: MIT
import copy
import ctypes
import json
from multiprocessing import Array, Value
import pytest

from zerorun_harness.api import InvalidEvidence, digest
from zerorun_harness.binding import (
    generate_binding,
    recorder,
    validate_binding,
    UnsupportedBinding,
)
from zerorun_harness.projection import project, validate_projection
from zerorun_harness._telemetry_protocol import PrimitiveError
from declarative_support import SOURCE, profile


@pytest.mark.parametrize(
    "value", [ctypes.c_int(4), ctypes.c_double(4), Value("i", 4), Value("d", 4)]
)
def test_actual_native_shared_scalar_read(value):
    assert project({"local": "x", "path": [{"member": "value"}]}, {"x": value}) == 4


@pytest.mark.parametrize(
    "value", [[1, 0], (1, 0), (ctypes.c_byte * 2)(1, 0), Array("b", [1, 0])]
)
def test_actual_native_commit_index_read(value):
    assert (
        project({"local": "x", "path": [{"index_local": "i"}]}, {"x": value, "i": 1})
        == 0
    )


def test_nested_snapshot_and_explicit_native_missing_sentinel():
    state = {
        "report": {"ok": ["case-a"], "failed": []},
        "pair": ({"case-a": "PASSED"}, True),
    }
    assert (
        json.loads(project({"local": "report", "encoding": "json"}, state))
        == state["report"]
    )
    assert (
        project({"local": "pair", "path": [{"index": 0}, {"index": "case-a"}]}, state)
        == "PASSED"
    )
    assert (
        project(
            {"local": "report", "path": [{"index": "absent"}], "default": "MISSING"},
            state,
        )
        == "MISSING"
    )
    with pytest.raises(KeyError):
        project({"local": "nonexistent", "default": "MISSING"}, state)


def test_arbitrary_native_methods_and_properties_are_never_invoked():
    class Unexpected:
        @property
        def value(self):
            raise AssertionError("native property must not run")

        def __getitem__(self, key):
            raise AssertionError("native custom indexing must not run")

    for path in [[{"member": "value"}], [{"index": 0}]]:
        with pytest.raises(PrimitiveError):
            project({"local": "x", "path": path}, {"x": Unexpected()})


def test_ctypes_subclass_custom_indexing_is_not_invoked():
    calls = []

    class Custom(ctypes.c_int * 2):
        def __getitem__(self, index):
            calls.append(index)
            return 99

    with pytest.raises(PrimitiveError):
        project({"local": "x", "path": [{"index": 0}]}, {"x": Custom(1, 2)})
    assert calls == []


def test_ctypes_custom_metaclass_accessors_are_not_invoked():
    calls = []

    class NativeMeta(type(ctypes.c_int * 1)):
        def __getattribute__(cls, name):
            calls.append(name)
            return super().__getattribute__(name)

    class NativeArray(ctypes.Array, metaclass=NativeMeta):
        _type_ = ctypes.c_int
        _length_ = 2

    value = NativeArray(1, 2)
    calls.clear()
    with pytest.raises(PrimitiveError):
        project({"local": "x", "path": [{"index": 0}]}, {"x": value})
    assert calls == []


def test_native_index_selected_from_a_primitive_path_reads_stored_cell():
    spec = {
        "local": "native_map",
        "path": [{"index_local": "native_tokens", "index_path": [1]}],
    }
    validate_projection(spec)
    assert (
        project(
            spec,
            {"native_map": {"test-a": "PASSED"}, "native_tokens": ["PASSED", "test-a"]},
        )
        == "PASSED"
    )
    with pytest.raises(PrimitiveError):
        project(spec, {"native_map": {"test-a": "PASSED"}, "native_tokens": []})


@pytest.mark.parametrize(
    "bad",
    [
        {"local": "x", "path": [{"member": "__class__"}]},
        {"local": "x", "path": [{"index": True}]},
        {"local": "x", "path": [{"call": "get_value"}]},
        {"local": "x", "path": [{"index_local": "__zr_return"}]},
        {"local": "x", "path": [{"index": 0}] * 9},
        {"local": "x", "encoding": "repr"},
        {"local": "x", "default": None},
        {"local": "x", "return": True},
    ],
)
def test_unbounded_or_executable_projection_refused(bad):
    with pytest.raises(InvalidEvidence):
        validate_projection(bad)


def one_site(function, anchor, position, projection):
    p = profile()
    p["id"] = "return-binding-control"
    p["facts"] = {"raw": {"flag": "int"}}
    p["sites"] = {
        "return": dict(
            kind="raw",
            path="native.py",
            function=function,
            anchor=anchor,
            position=position,
            multiplicity=1,
            projection={
                **{
                    k: {"literal": v}
                    for k, v in dict(
                        run="r", candidate="c", obligation=0, phase="b", attempt=1
                    ).items()
                },
                "flag": projection,
            },
            justification="Native return projection control",
        )
    }
    p["rules"] = [
        dict(
            id="self-preservation",
            check="C2",
            producer="raw",
            consumer="raw",
            keys=list(p["identity"]),
            when=None,
            source_field="flag",
            target_field="flag",
            operator="identity",
            statuses=[],
            target_mapping=None,
            requires=["return"],
            justification="Exact native identity control",
        )
    ]
    return p


def run_binding(p, source, args):
    b = generate_binding(p, {"native.py": source})
    events = []

    class Sink:
        def emit(self, value):
            events.append(value)
            return True

    scope = {"__zr_observe": recorder(p, b, Sink(), 123)}
    exec(compile(b["transformed"]["native.py"], "native.py", "exec"), scope)
    result = scope["outer"](*args)
    return b, events, result


def test_return_value_evaluated_exactly_once_and_same_object_returned():
    source = """def outer(fn):
    return fn()
"""
    p = one_site(
        "outer", "return fn()", "return_value", {"return": True, "path": [{"index": 0}]}
    )
    called = []
    original = [7]

    def native():
        called.append(True)
        return original

    _, events, result = run_binding(p, source, [native])
    assert result is original and called == [True]
    assert events[0]["values"] == {"flag": 7}


def test_return_exception_preserves_native_exception_without_callback():
    source = """def outer(fn):
    return fn()
"""
    p = one_site("outer", "return fn()", "return_value", {"return": True})
    b = generate_binding(p, {"native.py": source})
    events = []
    scope = {"__zr_observe": lambda *args: events.append(args)}
    exec(b["transformed"]["native.py"], scope)

    def native():
        raise TimeoutError("native boundary")

    with pytest.raises(TimeoutError, match="native boundary"):
        scope["outer"](native)
    assert events == []


def test_return_finally_behavior_and_nested_lexical_function_preserved():
    source = """def outer(log):
    unrelated = lambda x: x + 100
    def inner():
        try:
            return 7
        finally:
            log.append("finally")
    return inner()
"""
    p = one_site("outer.inner", "return 7", "return_value", {"return": True})
    log = []
    _, events, result = run_binding(p, source, [log])
    assert result == 7 and log == ["finally"] and events[0]["values"] == {"flag": 7}


def test_before_return_stays_before_operand_evaluation_when_both_sites_bound():
    source = """def outer(fn):
    state = [0]
    return fn(state)
"""
    p = one_site(
        "outer",
        "return fn(state)",
        "before_return",
        {"local": "state", "path": [{"index": 0}]},
    )
    p["sites"]["returned"] = copy.deepcopy(p["sites"]["return"])
    p["sites"]["returned"]["position"] = "return_value"
    p["sites"]["returned"]["projection"]["flag"] = {
        "return": True,
        "path": [{"index": 0}],
    }
    p["rules"][0]["requires"].append("returned")

    def native(state):
        state[0] = 1
        return state

    _, events, result = run_binding(p, source, [native])
    assert result == [1] and [e["values"]["flag"] for e in events] == [0, 1]


def test_return_operand_is_distinguished_from_finally_overridden_return():
    source = """def outer():
    try:
        return 7
    finally:
        return 9
"""
    p = one_site("outer", "return 7", "return_value", {"return": True})
    _, events, result = run_binding(p, source, [])
    assert events[0]["values"]["flag"] == 7 and result == 9


def test_before_and_after_commit_observe_distinct_native_values():
    source = """def outer(log):
    state = [0]
    state[0] = 1
    return state
"""
    p = one_site(
        "outer", "state[0] = 1", "before", {"local": "state", "path": [{"index": 0}]}
    )
    p["sites"]["after"] = copy.deepcopy(p["sites"]["return"])
    p["sites"]["after"]["position"] = "after"
    p["rules"][0]["requires"].append("after")
    _, events, result = run_binding(p, source, [[]])
    assert result == [1]
    assert [e["values"]["flag"] for e in events] == [0, 1]


def test_old_binding_grammar_regenerates_without_retargeting():
    p = profile()
    old = generate_binding(p, {"native.py": SOURCE}, grammar_version="1.0.0")
    validate_binding(p, old)
    new = generate_binding(p, {"native.py": SOURCE})
    assert old["transformed"] == new["transformed"]
    assert (
        old["sha256"] != new["sha256"]
        and old["grammar_version"] == "1.0.0"
        and new["grammar_version"] == "1.2.0"
    )


def test_old_declaration_literal_admission_preserved_separately_from_wire_bounds():
    p = profile()
    p["sites"]["accept"]["projection"]["candidate"] = {"literal": "x" * 1025}
    b = generate_binding(p, {"native.py": SOURCE}, grammar_version="1.0.0")
    assert validate_binding(p, b)["grammar_version"] == "1.0.0"


def test_native_compile_failure_is_typed_binding_refusal():
    p = one_site("outer", "return 7", "return_value", {"return": True})
    with pytest.raises(UnsupportedBinding, match="cannot compile"):
        generate_binding(p, {"native.py": "break\ndef outer():\n    return 7\n"})


@pytest.mark.parametrize(
    "module",
    [
        "VALUE=7\n",
        '__all__=["VALUE"]\nVALUE=7\n',
    ],
)
def test_wildcard_constant_dependency_is_original_source_qualified(module):
    p = one_site("outer", "return VALUE", "return_value", {"return": True})
    b = generate_binding(
        p,
        {
            "native.py": "from config import *\ndef outer():\n    return VALUE\n",
            "config.py": module,
        },
    )
    assert "config.py" in b["original_sources"]
    validate_binding(p, b)


@pytest.mark.parametrize(
    "module",
    [None, "import os\n", "VALUE=compute()\n", "locals=7\n", '__all__=["missing"]\n'],
)
def test_unknown_executable_or_shadowing_wildcard_namespace_refused(module):
    p = one_site("outer", "return VALUE", "return_value", {"return": True})
    sources = {"native.py": "from config import *\ndef outer():\n    return VALUE\n"}
    if module is not None:
        sources["config.py"] = module
    with pytest.raises(UnsupportedBinding):
        generate_binding(p, sources)


def test_new_projection_cannot_be_labeled_old_binding_grammar():
    p = one_site("outer", "return 7", "return_value", {"return": True})
    with pytest.raises(InvalidEvidence, match="Old grammar"):
        generate_binding(
            p, {"native.py": "def outer():\n return 7\n"}, grammar_version="1.0.0"
        )


def test_native_return_name_collision_refused():
    p = one_site("outer", "return __zr_return", "return_value", {"return": True})
    with pytest.raises(UnsupportedBinding, match="shadows"):
        generate_binding(
            p, {"native.py": "def outer():\n __zr_return = 7\n return __zr_return\n"}
        )


@pytest.mark.parametrize(
    "declaration",
    [
        "import os as __zr_return",
        "from os import path as __zr_return",
        "global __zr_return",
        "def locals():\n    return 3",
        "class locals:\n    pass",
        "try:\n    pass\nexcept Exception as __zr_return:\n    pass",
        "match 1:\n    case __zr_return:\n        pass",
        "match []:\n    case [*__zr_return]:\n        pass",
        "match {}:\n    case {**__zr_return}:\n        pass",
    ],
)
def test_all_native_plumbing_binding_forms_refused(declaration):
    p = one_site("outer", "return 7", "return_value", {"return": True})
    source = declaration + "\n\ndef outer():\n    return 7\n"
    with pytest.raises(UnsupportedBinding, match="shadows"):
        generate_binding(p, {"native.py": source})


def test_identity_context_cannot_override_native_fields_or_hide_a_checker():
    p = one_site("outer", "return 7", "return_value", {"return": True})
    p["sites"]["return"]["projection"]["run"] = {"context": "run"}
    b = generate_binding(p, {"native.py": "def outer():\n    return 7\n"})

    class Sink:
        def emit(self, value):
            return value

    context = {"run": "actual-run"}
    cb = recorder(p, b, Sink(), 123, context=context)
    context["run"] = "changed-after-construction"
    event = cb("return", {"run": "native-local-is-not-overwritten", "__zr_return": 7})
    assert event["identity"]["run"] == "actual-run" and event["values"]["flag"] == 7
    for bad in [{}, {"run": False}, {"run": "r", "expected_grade": 7}]:
        with pytest.raises(InvalidEvidence):
            recorder(p, b, Sink(), 123, context=bad)
    p["sites"]["return"]["projection"]["flag"] = {"context": "expected_grade"}
    with pytest.raises(InvalidEvidence, match="identity metadata"):
        generate_binding(p, {"native.py": "def outer():\n    return 7\n"})


def test_context_validation_never_invokes_arbitrary_copy_handler():
    p = one_site("outer", "return 7", "return_value", {"return": True})
    p["sites"]["return"]["projection"]["run"] = {"context": "run"}
    b = generate_binding(p, {"native.py": "def outer():\n    return 7\n"})

    class HiddenCopy:
        def __deepcopy__(self, memo):
            raise AssertionError("must not execute")

    with pytest.raises(InvalidEvidence, match="primitive bounds"):
        recorder(p, b, None, 123, context={"run": HiddenCopy()})


def test_oversized_snapshot_fails_without_mutating_native_state():
    state = {"x": {"key": list(range(65))}}
    before = copy.deepcopy(state)
    with pytest.raises(PrimitiveError):
        project({"local": "x", "encoding": "json"}, state)
    assert state == before
