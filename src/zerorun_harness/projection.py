# SPDX-License-Identifier: MIT
"""Finite read-only projections from known native primitive containers.

No candidate expression, callable, arbitrary property or plugin conversion is
executed here. Native shared scalar/array reads are qualified separately against
the original execution; they can still alter timing under the cooperative model.
"""

import ctypes
import json
from _multiprocessing import SemLock
from multiprocessing.sharedctypes import Synchronized, SynchronizedArray
from multiprocessing.synchronize import Lock, RLock
from types import BuiltinMethodType, GetSetDescriptorType

from .api import InvalidEvidence
from ._telemetry_protocol import PrimitiveError, primitives

ACTIVATION_LOCAL = '__zr_activation'

SCALARS = {
    ctypes.c_bool,
    ctypes.c_byte,
    ctypes.c_ubyte,
    ctypes.c_short,
    ctypes.c_ushort,
    ctypes.c_int,
    ctypes.c_uint,
    ctypes.c_long,
    ctypes.c_ulong,
    ctypes.c_longlong,
    ctypes.c_ulonglong,
    ctypes.c_float,
    ctypes.c_double,
}
RETURN_LOCAL = "__zr_return"
ARRAY_META = type(ctypes.c_int * 1)
COLLECTION_SCAN_LIMIT = 4096
SCALAR_BASE = ctypes.c_int.__bases__[0]
SCALAR_VALUE = type.__getattribute__(SCALAR_BASE, "__dict__")["value"]
SCALAR_NAMES = {"__module__", "_type_", "__dict__", "__weakref__", "__doc__",
                "__ctype_be__", "__ctype_le__"}


def exact_kind(value, *kinds):
    # Equality/set membership of type objects can execute candidate metaclasses.
    return any(type(value) is kind for kind in kinds)


def native_scalar_value(value):
    """Validate standard scalar class plumbing before a direct native read."""
    kind=type(value)
    if not exact_kind(value,*SCALARS):
        raise PrimitiveError("Unsupported native scalar type")
    namespace=type.__getattribute__(kind,"__dict__")
    if (not set(namespace)<=SCALAR_NAMES
            or type.__getattribute__(kind,"__bases__")!=(SCALAR_BASE,)
            or type(SCALAR_VALUE) is not GetSetDescriptorType
            or SCALAR_VALUE.__objclass__ is not SCALAR_BASE
            or SCALAR_VALUE.__name__!="value"
            or type.__getattribute__(SCALAR_BASE,"__dict__")["value"] is not SCALAR_VALUE):
        raise PrimitiveError("Altered native scalar class plumbing")
    return SCALAR_VALUE.__get__(value,kind)


def native_array_type(kind):
    """Only standard generated ctypes arrays, never user-overridden subclasses."""
    if type(kind) is not ARRAY_META or type.__getattribute__(kind, "__bases__") != (
        ctypes.Array,
    ):
        return False
    namespace = type.__getattribute__(kind, "__dict__")
    if not set(namespace) <= {
        "_type_",
        "_length_",
        "__module__",
        "__doc__",
        "__dict__",
        "__weakref__",
    }:
        return False
    element, length = namespace.get("_type_"), namespace.get("_length_")
    return (
        any(element is scalar for scalar in SCALARS)
        and type(length) is int
        and kind is element * length
    )


def validate_projection(spec):
    def require(ok, message):
        if not ok:
            raise InvalidEvidence(message)

    def primitive(value):
        try:
            primitives(value)
        except PrimitiveError as exc:
            raise InvalidEvidence(
                "Projection primitive exceeds declared bounds"
            ) from exc

    require(type(spec) is dict, "Invalid primitive projection")
    if "activation" in spec:
        require(spec == {"activation":True} and spec['activation'] is True,
                "Activation is an exact acquisition identity projection")
        return
    if "literal" in spec:
        require(
            set(spec) == {"literal"}
            and exact_kind(spec["literal"], str, bool, int, float),
            "Invalid primitive literal projection",
        )
        # Preserve version-1 declaration admission; finite wire bounds are
        # enforced on the actual emitted value, as in binding grammar 1.0.0.
        return
    origins = set(spec) & {"local", "return", "context", "item", "ordinal"}
    require(
        len(origins) == 1
        and set(spec) <= origins | {"path", "default", "encoding", "size", "contains"},
        "Projection requires one native origin and finite path",
    )
    if "local" in spec or "context" in spec:
        key = "local" if "local" in spec else "context"
        require(
            type(spec[key]) is str
            and spec[key].isidentifier()
            and not spec[key].startswith("__zr_"),
            "Invalid native local/context projection",
        )
        if key == "context":
            require(
                set(spec) == {"context"},
                "Identity context cannot compute derived facts",
            )
    elif "return" in spec:
        require(spec["return"] is True, "Invalid native return projection")
    else:
        key = "item" if "item" in spec else "ordinal"
        require(spec[key] is True, "Invalid native batch projection")
        if key == "ordinal":
            require(set(spec) == {"ordinal"}, "Native ordinal cannot compute derived facts")
    path = spec.get("path", [])
    require(type(path) is list and len(path) <= 8, "Native projection path cap")
    for step in path:
        require(
            type(step) is dict and 1 <= len(step) <= 2, "Invalid native projection step"
        )
        if "index" in step:
            require(
                set(step) == {"index"} and exact_kind(step["index"], str, int),
                "Index must be primitive string/integer",
            )
        elif "index_local" in step:
            require(
                set(step) <= {"index_local", "index_path"}
                and type(step["index_local"]) is str
                and step["index_local"].isidentifier()
                and not step["index_local"].startswith("__zr_"),
                "Invalid native index local",
            )
            require(
                type(step.get("index_path", [])) is list
                and len(step.get("index_path", [])) <= 4
                and all(exact_kind(v, int, str) for v in step.get("index_path", [])),
                "Native index projection must be a bounded literal path",
            )
        elif "stored" in step:
            require(set(step)=={"stored","record"} and type(step["stored"]) is str
                    and step["stored"].isidentifier() and not step["stored"].startswith('_')
                    and type(step["record"]) is str and 0<len(step["record"])<=256,
                    "Invalid declared native stored-field projection")
        else:
            require(
                step == {"member": "value"},
                "Only native scalar value member is supported",
            )
    if "default" in spec:
        require(
            exact_kind(spec["default"], str, int, bool, float),
            "Missing-index default must be primitive",
        )
        primitive(spec["default"])
    require(
        len(set(spec) & {"size", "contains", "encoding"}) <= 1,
        "Collection terminal operations cannot be combined",
    )
    if "size" in spec:
        require(spec["size"] is True, "Native cardinality requires size=true")
    if "contains" in spec:
        selector = spec["contains"]
        require(type(selector) is dict, "Invalid native membership selector")
        if set(selector) == {"literal"}:
            require(
                exact_kind(selector["literal"], str, int),
                "Membership literal must be exact string/integer",
            )
            primitive(selector["literal"])
        else:
            require(
                set(selector) == {"local"}
                and type(selector["local"]) is str
                and selector["local"].isidentifier()
                and not selector["local"].startswith("__zr_"),
                "Membership selector must be a native local or literal",
            )
    require(
        "encoding" not in spec or spec["encoding"] in ("json", "sorted_json", "number_json"),
        "Unsupported native snapshot encoding",
    )


def project(spec, local_state, context=None, *, item=None, ordinal=None, records=None):
    """Read one declared field; absent indexing can use a declared raw sentinel."""
    if "literal" in spec:
        return spec["literal"]
    if "context" in spec:
        return context[spec["context"]]
    if "activation" in spec:
        value = local_state.get(ACTIVATION_LOCAL)
        if type(value) is not int or not 1 <= value <= 32768:
            raise PrimitiveError('Missing/unqualified native activation identity')
        return value
    if "item" in spec:
        value = item
    elif "ordinal" in spec:
        value = ordinal
    else:
        value = local_state[spec.get("local", RETURN_LOCAL)]
    for step in spec.get("path", []):
        if "stored" in step:
            from .records import RecordRegistry
            if type(records) is not RecordRegistry:
                raise PrimitiveError("Native stored field requires qualified runtime types")
            value=records.read(value,step["record"],step["stored"])
            continue
        if "member" in step:
            if type(value) is Synchronized:
                raw, semaphore = synchronized_parts(value)
                if not exact_kind(raw, *SCALARS):
                    raise PrimitiveError("Unsupported native synchronized scalar")
                with semaphore:
                    value = native_scalar_value(raw)
            elif exact_kind(value, *SCALARS):
                value = native_scalar_value(value)
            else:
                raise PrimitiveError("Arbitrary native properties are not projected")
            continue
        index = step["index"] if "index" in step else local_state[step["index_local"]]
        for selector in step.get("index_path", []):
            try:
                index = read_index(index, selector)
            except (KeyError, IndexError):
                raise PrimitiveError("Missing native index identity") from None
        try:
            value = read_index(value, index)
        except (IndexError, KeyError):
            if "default" not in spec:
                raise PrimitiveError("Missing native projected index") from None
            value = spec["default"]
            break
    if "size" in spec:
        value = native_size(value)
    elif "contains" in spec:
        selector = spec["contains"]
        needle = (selector["literal"] if "literal" in selector
                  else local_state[selector["local"]])
        value = native_contains(value, needle)
    if spec.get("encoding") == "sorted_json":
        if type(value) is not set or len(value) > 64:
            raise PrimitiveError("Native set snapshot requires a bounded exact set")
        if (any(not exact_kind(item, str, int) for item in value)
                or (value and not all(type(item) is type(next(iter(value))) for item in value))):
            raise PrimitiveError("Native set snapshot requires homogeneous strings/integers")
        value = sorted(value)
    if spec.get("encoding") == "number_json":
        if not exact_kind(value,int,float):
            raise PrimitiveError("Native number encoding requires exact integer/float")
        # Tokens preserve missing-vs-present NaN/Inf, signed zero and finite
        # values. No zero substitution or eligibility classification occurs.
        if type(value) is int:
            primitives(value)
        value=json.dumps(value,allow_nan=True,separators=(",",":"))
    if spec.get("encoding") in ("json", "sorted_json"):
        primitives(value)
        value = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    primitives(value)
    return value


def native_size(value):
    """Cardinality without user-defined length, array or wrapper dispatch."""
    kind = type(value)
    if exact_kind(value, dict, list, tuple, set):
        return len(value)
    if kind is SynchronizedArray:
        raw, semaphore = synchronized_parts(value)
        if not native_array_type(type(raw)):
            raise PrimitiveError("Unsupported native synchronized array")
        with semaphore:
            return len(raw)
    if native_array_type(kind):
        return len(value)
    raise PrimitiveError("Arbitrary native cardinality is not projected")


def native_contains(value, needle):
    """Read membership only after proving equality/hash cannot call user code."""
    if not exact_kind(needle, str, int):
        raise PrimitiveError("Native membership selector must be string/integer")
    primitives(needle)
    if not exact_kind(value, dict, list, tuple, set):
        raise PrimitiveError("Arbitrary native membership is not projected")
    if len(value) > COLLECTION_SCAN_LIMIT:
        raise PrimitiveError("Native membership scan exceeds declared bound")
    if any(not exact_kind(item, str, int) for item in value):
        raise PrimitiveError("Native membership requires string/integer elements or keys")
    return needle in value


def synchronized_parts(value):
    """Validate standard wrapper plumbing without dispatching instance methods."""
    namespace = object.__getattribute__(value, "__dict__")
    if (
        type(namespace) is not dict
        or len(namespace) != 4
        or any(type(k) is not str for k in namespace)
        or set(namespace) != {"_obj", "_lock", "acquire", "release"}
    ):
        raise PrimitiveError("Altered native synchronized wrapper")
    lock = namespace["_lock"]
    if not exact_kind(lock, Lock, RLock):
        raise PrimitiveError("Unsupported native synchronized lock")
    try:
        semaphore = object.__getattribute__(lock, "_semlock")
    except AttributeError:
        raise PrimitiveError("Missing native semaphore") from None
    if type(semaphore) is not SemLock:
        raise PrimitiveError("Unsupported native semaphore")
    for name in ("acquire", "release"):
        method = namespace[name]
        if (
            type(method) is not BuiltinMethodType
            or method.__self__ is not semaphore
            or method.__name__ != name
        ):
            raise PrimitiveError("Altered native synchronized method")
    return namespace["_obj"], semaphore


def read_index(value, index):
    """A single read on a statically bounded set of exact native containers."""
    if not exact_kind(index, int, str):
        raise PrimitiveError("Native index must be exact integer/string")
    kind = type(value)
    if kind is dict:
        # Primitive key equality cannot invoke a candidate object's hash.
        if any(not exact_kind(k, str, int) for k in value):
            raise PrimitiveError("Native map has unsupported key types")
    elif exact_kind(value, list, tuple) or kind is SynchronizedArray or native_array_type(kind):
        if type(index) is not int:
            raise PrimitiveError("Native sequence index must be integer")
        if kind is SynchronizedArray:
            raw, semaphore = synchronized_parts(value)
            if not native_array_type(type(raw)):
                raise PrimitiveError("Unsupported native synchronized array")
            with semaphore:
                return raw[index]
    else:
        raise PrimitiveError("Arbitrary native indexing is not projected")
    return value[index]
