# SPDX-License-Identifier: MIT
"""Bounded parent/one-native-child acquisition; v1 protocol remains unchanged.

Each producer owns a distinct preallocated nonblocking pipe and fresh emitter.
Transport/lifecycle facts do not assert domain semantics or candidate acceptance.
"""

import errno
import ctypes
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from ._telemetry_protocol import (
    Collector, Emitter, MAX_FRAME, MAX_TRACE, PrimitiveError,
    UnsupportedTransport, primitives,
)
from .api import InvalidEvidence, canonical, fingerprint
from .projection import SCALARS, native_array_type, synchronized_parts
from multiprocessing.sharedctypes import Synchronized, SynchronizedArray

SCHEMA = "zerorun-telemetry-pair/1"
COUNTERS = ("attempted", "emitted", "dropped", "rejected", "partial")
NO_EXIT = -2147483647
STATE_FIELDS = (
    "parent_pid", "worker_pid", "worker_parent_pid", "expected_worker_pid",
    "fork_attempts", "fork_error", "unexpected_fork", "observer_error",
    "worker_entered", "worker_finished", "worker_normal", "worker_exitcode",
    "parent_completed", "parent_setup_error", "worker_close_error",
) + tuple("worker_" + name for name in COUNTERS)


def _runtime_supported(start_method):
    return (
        start_method == "fork" and sys.platform == "linux"
        and sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 16) and sys.flags.optimize == 0
    )


def _close(fd):
    if fd is not None:
        try:
            os.close(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise


def _process_types():
    return tuple(
        getattr(mp.context, name)
        for name in ("Process", "ForkProcess")
        if hasattr(mp.context, name)
    )


def _popen_type():
    from multiprocessing.popen_fork import Popen
    return Popen


def native_process_snapshot(process):
    """Read exact fork-process cached state; never poll/join or invoke properties."""
    if not any(type(process) is allowed for allowed in _process_types()):
        raise UnsupportedTransport("Native process class is not qualified fork")
    namespace = object.__getattribute__(process, "__dict__")
    if type(namespace) is not dict:
        raise UnsupportedTransport("Custom native process namespace")
    popen = namespace.get("_popen")
    if type(popen) is not _popen_type():
        raise UnsupportedTransport("Native process has not started with fork")
    state = object.__getattribute__(popen, "__dict__")
    if type(state) is not dict:
        raise UnsupportedTransport("Custom native process backend namespace")
    pid, code, parent = state.get("pid"), state.get("returncode"), namespace.get("_parent_pid")
    if (
        type(pid) is not int or pid <= 0
        or type(parent) is not int or parent <= 0
        or (code is not None and type(code) is not int)
    ):
        raise UnsupportedTransport("Invalid cached native process state")
    return {"pid": pid, "parent_pid": parent, "exitcode": code}


def native_buffer_snapshot(local_state, names):
    """Actual fork-inherited object/backing identities; no cross-run meaning."""
    result = {}
    for name in names:
        if type(local_state) is not dict or name not in local_state:
            raise PrimitiveError("Missing declared native buffer local")
        wrapper = local_state[name]
        if type(wrapper) is not Synchronized and type(wrapper) is not SynchronizedArray:
            raise PrimitiveError("Only exact native synchronized buffers are admitted")
        raw, _ = synchronized_parts(wrapper)
        if not native_array_type(type(raw)) and not any(type(raw) is t for t in SCALARS):
            raise PrimitiveError("Native buffer backing type is not qualified")
        result[name] = {
            "wrapper": id(wrapper), "backing": id(raw),
            "address": ctypes.addressof(raw), "bytes": ctypes.sizeof(raw),
        }
    return result


class _Lifecycle:
    def __init__(self, session, role, function, local_state):
        self.session, self.role, self.function = session, role, function
        self.local_state = local_state

    def __enter__(self):
        self.session.worker_enter(self.role, self.function, self.local_state)
        return None

    def __exit__(self, exc_type, exc_value, traceback):
        self.session.worker_finished(
            normal_return=exc_type is None,
            exception_name=None if exc_type is None else type.__getattribute__(exc_type, "__name__"),
        )
        return False


class Session:
    """Acquisition plumbing installed by a trusted source-pinned adapter.

    An observer factory receives (emitter, actual_pid). It must construct a fresh
    recorder rather than copying a pre-fork sequence closure.
    """

    def __init__(self, parent_fd, worker_fd, state, *, max_trace_bytes=MAX_TRACE):
        self.state = state
        self.parent_fd, self.worker_fd = parent_fd, worker_fd
        self._close = os.close
        self._getpid, self._getppid = os.getpid, os.getppid
        self.origin_pid = self._getpid()
        self.state["parent_pid"].value = self.origin_pid
        self.role = "parent"
        self.emitter = Emitter(parent_fd)
        self.observer = None
        self.factory = None
        self.start_site = None
        self.process_local = None
        self.native_process = None
        self.closed = False
        self.worker_exception = None
        self._lifecycle_active = False
        self._lifecycle_function = None
        self.buffer_locals = ()
        self.max_trace_bytes = max_trace_bytes

    def install_observer(
        self, factory, *, child_start_site="native-child-started", process_local="p",
        buffer_locals=(),
    ):
        if (
            self.factory is not None or not callable(factory)
            or type(child_start_site) is not str or not child_start_site
            or type(process_local) is not str or not process_local.isidentifier()
        ):
            raise UnsupportedTransport("Invalid/repeated observer initialization")
        if (
            (type(buffer_locals) is not tuple and type(buffer_locals) is not list)
            or len(buffer_locals) > 8
            or any(type(name) is not str or not name.isidentifier() for name in buffer_locals)
            or len(set(buffer_locals)) != len(buffer_locals)
        ):
            raise UnsupportedTransport("Invalid native buffer identity declaration")
        self.buffer_locals = tuple(buffer_locals)
        self.factory = factory
        self.start_site, self.process_local = child_start_site, process_local
        self.observer = factory(self.emitter, self.origin_pid)
        if not callable(self.observer):
            raise UnsupportedTransport("Observer factory did not return a callback")
        os.register_at_fork(
            before=self._before_fork, after_in_parent=self._after_parent,
            after_in_child=self._after_child,
        )

    def _before_fork(self):
        # No native branch changes: unsupported extra forks poison acquisition.
        if self._getpid() != self.origin_pid or self.closed:
            self.state["unexpected_fork"].value = 1
            return
        self.state["fork_attempts"].value += 1
        if self.state["fork_attempts"].value != 1:
            self.state["unexpected_fork"].value = 1

    def _after_parent(self):
        if self._getpid() == self.origin_pid and self.worker_fd is not None:
            try:
                self._close(self.worker_fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    self.state["worker_close_error"].value = 1
            self.worker_fd = None

    def _after_child(self):
        # Exceptions raised by Python at-fork callbacks are otherwise ignored.
        # Record initialization failure explicitly; never imply native coverage.
        self.role = "worker"
        self.native_process = None
        self.observer = None
        try:
            if self.state["fork_attempts"].value != 1 or self.state["unexpected_fork"].value:
                self.state["unexpected_fork"].value = 1
                self._close(self.parent_fd)
                if self.worker_fd is not None:
                    self._close(self.worker_fd)
                self.parent_fd = self.worker_fd = None
                return
            self._close(self.parent_fd)
            self.parent_fd = None
            pid = self._getpid()
            self.state["worker_pid"].value = pid
            self.state["worker_parent_pid"].value = self._getppid()
            self.emitter = Emitter(self.worker_fd)
            self.observer = self.factory(self.emitter, pid)
            if not callable(self.observer):
                raise UnsupportedTransport("Child observer factory failed")
        except Exception:
            self.state["observer_error"].value = 1

    def child_started(self, process):
        if self.role != "parent" or self._getpid() != self.origin_pid:
            self.state["unexpected_fork"].value = 1
            return False
        try:
            native = native_process_snapshot(process)
        except UnsupportedTransport:
            self.state["fork_error"].value = 1
            return False
        if (
            native["parent_pid"] != self.origin_pid
            or self.state["expected_worker_pid"].value
        ):
            self.state["fork_error"].value = 1
            return False
        self.native_process = process
        self.state["expected_worker_pid"].value = native["pid"]
        return True

    def refresh_child_state(self):
        if self.native_process is not None:
            try:
                native = native_process_snapshot(self.native_process)
                if native["pid"] != self.state["expected_worker_pid"].value:
                    self.state["fork_error"].value = 1
                self.state["worker_exitcode"].value = (
                    NO_EXIT if native["exitcode"] is None else native["exitcode"]
                )
            except UnsupportedTransport:
                self.state["fork_error"].value = 1

    def observe(self, site, local_state):
        if site == self.start_site:
            if type(local_state) is not dict or self.process_local not in local_state:
                self.state["fork_error"].value = 1
            else:
                self.child_started(local_state[self.process_local])
                if self.buffer_locals:
                    try:
                        buffers = native_buffer_snapshot(local_state, self.buffer_locals)
                    except PrimitiveError:
                        self.state["observer_error"].value = 1
                        buffers = {}
                    self.emitter.emit({
                        "schema": "zerorun-acquisition-lifecycle/1", "role": "parent",
                        "function": "native_process_start", "event": "child_started",
                        "exception": None, "buffers": buffers,
                    })
        if self.observer is None or self.emitter.producer != self._getpid():
            self.state["observer_error"].value = 1
            return False
        return self.observer(site, local_state)

    def lifecycle(self, role, function, local_state):
        if role != "worker" or type(function) is not str or not function:
            raise UnsupportedTransport("Only declared worker lifecycle is supported")
        # local_state is not inspected or rewritten by acquisition plumbing.
        return _Lifecycle(self, role, function, local_state)

    def worker_enter(self, role="worker", function="unsafe_execute", local_state=None):
        if (
            self.role != role or self._getpid() != self.state["worker_pid"].value
            or self._lifecycle_active or self.state["worker_entered"].value
        ):
            self.state["observer_error"].value = 1
            return False
        self._lifecycle_active = True
        self._lifecycle_function = function
        self.state["worker_entered"].value = 1
        try:
            buffers = native_buffer_snapshot(local_state, self.buffer_locals)
        except PrimitiveError:
            self.state["observer_error"].value = 1
            buffers = {}
        return self.emitter.emit({
            "schema": "zerorun-acquisition-lifecycle/1", "role": role,
            "function": function, "event": "enter", "exception": None,
            "buffers": buffers,
        })

    def worker_finished(self, *, normal_return, exception_name=None):
        if (
            self.role != "worker" or not self._lifecycle_active
            or type(normal_return) is not bool
            or (exception_name is not None and type(exception_name) is not str)
        ):
            self.state["observer_error"].value = 1
            return False
        self._lifecycle_active = False
        self.state["worker_finished"].value = 1
        self.state["worker_normal"].value = int(normal_return)
        self.worker_exception = exception_name
        self.emitter.emit({
            "schema": "zerorun-acquisition-lifecycle/1", "role": "worker",
            "function": self._lifecycle_function,
            "event": "return" if normal_return else "raise",
            "exception": exception_name,
        })
        for name in COUNTERS:
            self.state["worker_" + name].value = getattr(self.emitter, name)
        try:
            return self.emitter.seal()
        finally:
            if self.worker_fd is not None:
                try:
                    self._close(self.worker_fd)
                except OSError as exc:
                    if exc.errno != errno.EBADF:
                        self.state["worker_close_error"].value = 1
                self.worker_fd = None

    def finish_parent(self):
        self.refresh_child_state()
        self.closed = True
        try:
            return self.emitter.seal()
        finally:
            for name in ("parent_fd", "worker_fd"):
                fd = getattr(self, name)
                if fd is not None:
                    try:
                        self._close(fd)
                    except OSError as exc:
                        if exc.errno != errno.EBADF:
                            self.state["worker_close_error"].value = 1
                    setattr(self, name, None)


def _new_state(ctx):
    state = {name: ctx.RawValue("q", 0) for name in STATE_FIELDS}
    state["worker_exitcode"].value = NO_EXIT
    return state


def _state_values(state):
    return {name: int(value.value) for name, value in state.items()}


def graph_receipt(state, parent_pid):
    errors = []
    required = bool(state["worker_pid"] or state["expected_worker_pid"] or state["fork_attempts"])
    if state["parent_pid"] != parent_pid:
        errors.append("parent_identity")
    if required:
        if state["fork_attempts"] != 1:
            errors.append("fork_inventory")
        if not state["expected_worker_pid"] or state["expected_worker_pid"] != state["worker_pid"]:
            errors.append("native_child_identity")
        if state["worker_parent_pid"] != parent_pid:
            errors.append("native_parent_identity")
    for name in ("fork_error", "unexpected_fork", "observer_error", "worker_close_error"):
        if state[name]:
            errors.append(name)
    return {
        "parent_pid": parent_pid, "worker_pid": state["worker_pid"] or None,
        "expected_worker_pid": state["expected_worker_pid"] or None,
        "worker_parent_pid": state["worker_parent_pid"] or None,
        "worker_required": required, "fork_attempts": state["fork_attempts"],
        "intact": not errors, "errors": errors,
    }


def buffer_linkage(transports):
    rows = {}
    for role, event in (("parent", "child_started"), ("worker", "enter")):
        rows[role] = [
            p["event"]["buffers"] for p in transports[role]["events"]
            if p["event"].get("schema") == "zerorun-acquisition-lifecycle/1"
            and p["event"].get("event") == event and "buffers" in p["event"]
        ]
    if not rows["parent"] and not any(rows["worker"]):
        return {"required": False, "matched": None}
    matched = (
        len(rows["parent"]) == len(rows["worker"]) == 1
        and bool(rows["parent"][0]) and rows["parent"][0] == rows["worker"][0]
    )
    return {"required": True, "matched": matched,
            "parent": rows["parent"], "worker": rows["worker"],
            "scope": "Exact fork-inherited wrapper and backing identities within this capture"}


def _save_control(result, length, value):
    primitives(value)
    payload = canonical(value)
    if len(payload) > len(result):
        raise UnsupportedTransport("Native control result exceeds bound")
    result[:len(payload)] = payload
    length.value = len(payload)


def _parent(reads, writes, request, state, result, length):
    # Dedicated native process group lets the supervisor clean up grandchildren.
    os.setsid()
    for fd in reads:
        _close(fd)
    session = None
    try:
        sys.dont_write_bytecode = True
        # A fresh nonexistent cache prefix prevents stale pre-existing pyc use.
        sys.pycache_prefix = str(Path(request["group_receipt"]).parent / "no-bytecode")
        session = Session(writes[0], writes[1], state, max_trace_bytes=request['max_trace_bytes'])
        path = Path(request["adapter"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != request["adapter_sha256"]:
            raise UnsupportedTransport("Adapter changed before normal import")
        name = "_zerorun_trusted_pair_adapter"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if hashlib.sha256(path.read_bytes()).hexdigest() != request["adapter_sha256"]:
            raise UnsupportedTransport("Adapter changed during normal import")
        returned = module.run(session, request["argument"])
        state["parent_completed"].value = 1
        _save_control(result, length, {
            "returned": returned, "exception": None,
            "telemetry_counts": {name: getattr(session.emitter, name) for name in COUNTERS},
        })
    except BaseException as exc:
        if session is None or isinstance(exc, UnsupportedTransport):
            state["parent_setup_error"].value = 1
        _save_control(result, length, {
            "returned": None, "exception": type.__getattribute__(type(exc), "__name__"),
            "telemetry_counts": (
                {name: getattr(session.emitter, name) for name in COUNTERS}
                if session is not None else None
            ),
        })
        raise
    finally:
        if session is not None:
            session.finish_parent()
        else:
            for fd in writes:
                _close(fd)


def _terminate_group(parent_pid):
    try:
        os.killpg(parent_pid, signal.SIGKILL)
        return "SIGKILL"
    except ProcessLookupError:
        return "already_absent"


def _cleanup_owned_process(proc):
    actions = [_terminate_group(proc.pid)]
    if proc.is_alive():
        # The child may not yet have executed setsid. Its owned Process handle
        # remains safe to terminate even when the intended group does not exist.
        proc.kill()
        actions.append("owned_parent_SIGKILL")
        proc.join(3)
        # A concurrently started group/descendant must not survive that race.
        actions.append(_terminate_group(proc.pid))
    else:
        proc.join(3)
    return actions


def _linux_process_identity(pid):
    """Linux kernel start-time identity; never invoke a candidate Process API."""
    try:
        stat = (Path('/proc') / str(pid) / 'stat').read_text(encoding='ascii')
        number, _, suffix = stat.partition(' (')
        fields = suffix.rsplit(')', 1)[1].split()
        if int(number) != pid or len(fields) < 20 or not fields[19].isdecimal():
            return None
        return int(fields[19])
    except (OSError, UnicodeError, ValueError, IndexError):
        return None


def _record_owned_group(path, pid):
    # The child may not have reached setsid yet. Capture the kernel identity now
    # so an outer supervisor failure can safely target that exact owned PID.
    Path(path).write_text(json.dumps({"pid": pid, "starttime": _linux_process_identity(pid)}), encoding='ascii')


def _cleanup_recorded_group(path):
    if not path.is_file():
        return {"group_pid": None, "action": "no_group_receipt"}
    try:
        if path.stat().st_size > 256:
            return {"group_pid": None, "action": "invalid_group_receipt"}
        value = json.loads(path.read_text(encoding="ascii"))
        if (type(value) is not dict or set(value) != {"pid", "starttime"}
            or type(value["pid"]) is not int or value["pid"] <= 0
            or (value["starttime"] is not None and
                (type(value["starttime"]) is not int or value["starttime"] < 0))):
            return {"group_pid": None, "action": "invalid_group_receipt"}
        pid = value["pid"]
        live_identity = _linux_process_identity(pid)
        if live_identity is not None and live_identity != value["starttime"]:
            # An unrelated live leader may now own the reused numeric PID and
            # process group. Never signal it, even as a group cleanup attempt.
            return {"group_pid": pid, "action": "live_process_identity_mismatch",
                    "recorded_starttime": value["starttime"],
                    "direct_pid_fallback": None, "group_retry": None}
        action = _terminate_group(pid)
        fallback = None
        if (action == "already_absent" and value["starttime"] is not None
            and _linux_process_identity(pid) == value["starttime"]):
            pidfd = None
            try:
                pidfd = os.pidfd_open(pid)
                if _linux_process_identity(pid) == value["starttime"]:
                    # Signal the retained kernel process handle, not a PID that
                    # could be recycled after the identity check.
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                    fallback = "matching_owned_PID_SIGKILL"
                else:
                    fallback = "owned_PID_identity_changed"
            except ProcessLookupError:
                fallback = "owned_PID_already_absent"
            finally:
                if pidfd is not None:
                    os.close(pidfd)
            # The child can race from the barrier to setsid before its signal
            # takes effect. Any new descendants remain in this recorded group.
            retry = _terminate_group(pid)
        else:
            retry = None
        return {"group_pid": pid, "action": action,
                "recorded_starttime": value["starttime"],
                "direct_pid_fallback": fallback, "group_retry": retry}
    except (ValueError, TypeError):
        return {"group_pid": None, "action": "invalid_group_receipt"}
    except (OSError, UnicodeError):
        return {"group_pid": None, "action": "unreadable_group_receipt"}


def _close_owned(fd, owned):
    if fd in owned:
        owned.remove(fd)
        _close(fd)


def acquire(request, *, _collector_fault=None):
    """Supervisor-only implementation; internal faults are qualification controls."""
    if not _runtime_supported(request["start_method"]):
        raise UnsupportedTransport("Only Linux CPython 3.11.16/fork/optimize=0 is qualified")
    source = Path(request["adapter"]).read_bytes()
    if len(source) > 1024 * 1024 or hashlib.sha256(source).hexdigest() != request["adapter_sha256"]:
        raise UnsupportedTransport("Adapter source identity mismatch")
    maximum = request["max_trace_bytes"]
    if type(maximum) is not int or not 2 * MAX_FRAME <= maximum <= MAX_TRACE:
        raise UnsupportedTransport("Pair trace budget must be 8192..16777216 bytes")
    pipes = []
    try:
        for _ in range(2):
            rd, wr = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            pipes.append((rd, wr))
            if os.fpathconf(wr, "PC_PIPE_BUF") < MAX_FRAME:
                raise UnsupportedTransport("Insufficient atomic pipe size")
    except (OSError, UnsupportedTransport):
        for pair in pipes:
            for fd in pair:
                _close(fd)
        raise
    ctx = mp.get_context("fork")
    state = _new_state(ctx)
    result, length = ctx.RawArray("B", 65536), ctx.RawValue("I", 0)
    proc = ctx.Process(target=_parent, args=(
        [p[0] for p in pipes], [p[1] for p in pipes], request, state, result, length,
    ))
    start = time.monotonic()
    try:
        proc.start()
    except BaseException:
        for pair in pipes:
            for fd in pair:
                _close(fd)
        raise
    owned = {fd for pair in pipes for fd in pair}
    try:
        return _collect_started(
            request, state, result, length, proc, pipes, owned, start, _collector_fault
        )
    except BaseException:
        _cleanup_owned_process(proc)
        raise
    finally:
        for fd in list(owned):
            _close_owned(fd, owned)


def _collect_started(request, state, result, length, proc, pipes, owned, start, _collector_fault):
    _record_owned_group(request["group_receipt"], proc.pid)
    for _, wr in pipes:
        _close_owned(wr, owned)
    maximum = request["max_trace_bytes"]
    limits = (maximum // 2, maximum - maximum // 2)
    collectors = [Collector(proc.pid, limits[0]), None]
    pending = bytearray()
    selector = selectors.DefaultSelector()
    for role, (rd, _) in enumerate(pipes):
        selector.register(rd, selectors.EVENT_READ, role)
    eof, timed_out, cleanup = set(), False, []
    try:
        while proc.is_alive() or len(eof) != 2:
            if collectors[1] is None and state["worker_pid"].value:
                collectors[1] = Collector(state["worker_pid"].value, limits[1])
                if pending:
                    collectors[1].feed(pending)
                    pending.clear()
            if time.monotonic() - start >= request["wall_seconds"]:
                timed_out = True
                cleanup.extend(_cleanup_owned_process(proc))
                break
            for key, _ in selector.select(0.01):
                role = key.data
                if _collector_fault == ("stopped", role):
                    if collectors[role] is not None:
                        collectors[role].fail("collector_stopped")
                    continue
                if _collector_fault == ("broken", role):
                    if collectors[role] is not None:
                        collectors[role].fail("collector_closed_channel")
                    selector.unregister(key.fd)
                    _close_owned(key.fd, owned)
                    eof.add(role)
                    continue
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    eof.add(role)
                    selector.unregister(key.fd)
                elif collectors[role] is not None:
                    collectors[role].feed(data)
                elif len(pending) + len(data) <= limits[1]:
                    pending.extend(data)
                else:
                    state["observer_error"].value = 1
            if not proc.is_alive() and len(eof) == 2:
                break
        proc.join(3)
    finally:
        if proc.is_alive():
            cleanup.extend(_cleanup_owned_process(proc))
        values = _state_values(state)
        if (
            (values["worker_pid"] and values["worker_exitcode"] == NO_EXIT)
            or not graph_receipt(values, proc.pid)["intact"]
        ):
            cleanup.append(_terminate_group(proc.pid))
        selector.close()
        for rd, _ in pipes:
            _close_owned(rd, owned)
    values = _state_values(state)
    graph = graph_receipt(values, proc.pid)
    transports = {"parent": collectors[0].finish()}
    if collectors[1] is not None:
        transports["worker"] = collectors[1].finish()
    else:
        transports["worker"] = {
            "transport_intact": None if graph["worker_required"] else True,
            "events": [], "seals": [],
            "errors": ["missing_worker_channel"] if graph["worker_required"] else [],
            "received_bytes": len(pending), "stored_events": 0,
        }
    control = json.loads(bytes(result[:length.value])) if length.value else None
    counts = {
        "parent": control.get("telemetry_counts") if control else None,
        "worker": {name: values["worker_" + name] for name in COUNTERS},
    }
    for role, transport in transports.items():
        if transport["seals"] and counts[role] is not None:
            if any(transport["seals"][0][k] != counts[role][k] for k in COUNTERS):
                transport["transport_intact"] = False
                transport["errors"].append("control_plane_counter_disagreement")
    graph["buffers"] = buffer_linkage(transports)
    if graph["buffers"]["required"] and graph["buffers"]["matched"] is not True:
        graph["intact"] = False
        graph["errors"].append("native_buffer_identity")
    parent_complete = bool(
        values["parent_completed"] and proc.exitcode == 0 and not timed_out
        and control is not None and control["exception"] is None
    )
    worker_complete = bool(
        values["worker_entered"] and values["worker_finished"]
        and values["worker_normal"] and values["worker_exitcode"] == 0
    )
    intact = graph["intact"] and all(t["transport_intact"] is True for t in transports.values())
    return {
        "schema": SCHEMA, "status": (
            "UNSUPPORTED" if values["parent_setup_error"] else
            "CAPTURED" if parent_complete and intact else "INCOMPLETE"
        ),
        "supervisor_pid": os.getpid(), "graph": graph,
        "native": control, "transport": transports,
        "lifecycle": {
            "parent": {"complete": parent_complete, "exitcode": proc.exitcode},
            "worker": {
                "entered": bool(values["worker_entered"]),
                "function_finished": bool(values["worker_finished"]),
                "normal_return": bool(values["worker_normal"]),
                "cached_exitcode": None if values["worker_exitcode"] == NO_EXIT else values["worker_exitcode"],
                "complete": worker_complete,
            },
        },
        "outer_timeout": timed_out, "cleanup": cleanup,
        "state": values, "adapter_sha256": request["adapter_sha256"],
        "start_method": "fork", "optimize": sys.flags.optimize,
        "wall_seconds": time.monotonic() - start,
        "scope": "Producer transport and native lifecycle only; semantic sites are qualified separately",
    }


def capture_native_pair(
    adapter, adapter_sha256, argument, *, start_method="fork",
    wall_seconds=10, max_trace_bytes=MAX_TRACE,
):
    """Fresh isolated supervisor; adapter is normal-imported and source-pinned."""
    if not _runtime_supported(start_method):
        return {"schema": SCHEMA, "status": "UNSUPPORTED",
                "reason": "qualified runtime is Linux CPython 3.11.16/fork/optimize=0"}
    if not (type(wall_seconds) is int or type(wall_seconds) is float) or not 0 < wall_seconds <= 60:
        raise InvalidEvidence("Native wall budget must be positive and at most 60 seconds")
    if type(max_trace_bytes) is not int or not 2 * MAX_FRAME <= max_trace_bytes <= MAX_TRACE:
        raise InvalidEvidence("Pair trace byte budget outside supported bounds")
    canonical(argument)
    try:
        primitives(argument)
    except PrimitiveError as exc:
        raise InvalidEvidence(str(exc)) from exc
    path = Path(adapter).resolve()
    if (
        not fingerprint(adapter_sha256) or path.stat().st_size > 1024 * 1024
        or hashlib.sha256(path.read_bytes()).hexdigest() != adapter_sha256
    ):
        raise InvalidEvidence("Native adapter source identity/size mismatch")
    request = dict(adapter=str(path), adapter_sha256=adapter_sha256,
                   argument=argument, start_method=start_method,
                   wall_seconds=wall_seconds, max_trace_bytes=max_trace_bytes)
    with tempfile.TemporaryDirectory() as directory:
        inp, out = Path(directory) / "request.json", Path(directory) / "result.json"
        group_receipt = Path(directory) / "native-process-group.txt"
        request["group_receipt"] = str(group_receipt)
        inp.write_bytes(canonical(request))
        package_root = str(Path(__file__).resolve().parents[1])
        bootstrap = (
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
            "runpy.run_module('zerorun_harness._telemetry_multiprocess',run_name='__main__')"
        )
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", bootstrap, package_root, str(inp), str(out)],
            start_new_session=True,
        )
        try:
            code = proc.wait(timeout=wall_seconds + 15)
        except subprocess.TimeoutExpired:
            cleanup = _cleanup_recorded_group(group_receipt)
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return {"schema": SCHEMA, "status": "INCOMPLETE", "reason": "supervisor_deadline",
                    "failure_cleanup": cleanup}
        if code != 0 or not out.is_file():
            return {"schema": SCHEMA, "status": "INCOMPLETE", "reason": "supervisor_failure",
                    "failure_cleanup": _cleanup_recorded_group(group_receipt)}
        try:
            if out.stat().st_size > 2 * MAX_TRACE:
                raise InvalidEvidence("Pair supervisor receipt exceeds bound")
            receipt = json.loads(out.read_bytes())
            if (
                type(receipt) is not dict or receipt.get("schema") != SCHEMA
                or receipt.get("status") not in ("CAPTURED", "INCOMPLETE", "UNSUPPORTED")
            ):
                raise InvalidEvidence("Invalid pair supervisor receipt")
        except (OSError, ValueError, UnicodeError, InvalidEvidence):
            return {"schema": SCHEMA, "status": "INCOMPLETE", "reason": "invalid_supervisor_receipt",
                    "failure_cleanup": _cleanup_recorded_group(group_receipt)}
        receipt["caller_pid"] = os.getpid()
        receipt["transport_implementation_sha256"] = {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("_telemetry_multiprocess.py", "_telemetry_protocol.py")
        }
        return receipt


def main():
    request = json.loads(Path(sys.argv[1]).read_bytes())
    try:
        result = acquire(request)
    except UnsupportedTransport as exc:
        result = {"schema": SCHEMA, "status": "UNSUPPORTED", "reason": str(exc)}
    with Path(sys.argv[2]).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
