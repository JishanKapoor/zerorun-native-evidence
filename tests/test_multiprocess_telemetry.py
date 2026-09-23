"""Pure process/transport-state tests; real Linux controls run separately."""

from types import SimpleNamespace
import hashlib
import json
from pathlib import Path

import pytest

from zerorun_harness import _telemetry_multiprocess as t


class FakeEmitter:
    def __init__(self, fd):
        self.fd = fd
        self.producer = t.os.getpid()
        self.attempted = self.emitted = self.dropped = self.rejected = self.partial = 0
        self.sealed = False
        self.events = []

    def emit(self, event):
        self.attempted += 1
        self.emitted += 1
        self.events.append(event)
        return True

    def seal(self):
        self.sealed = True
        return True


@pytest.fixture
def session(monkeypatch):
    current = {"pid": 100, "ppid": 50}
    closes, forks, constructed = [], [], []
    monkeypatch.setattr(t.os, "getpid", lambda: current["pid"])
    monkeypatch.setattr(t.os, "getppid", lambda: current["ppid"])
    monkeypatch.setattr(t.os, "close", closes.append)
    monkeypatch.setattr(t.os, "register_at_fork", lambda **kw: forks.append(kw), raising=False)
    monkeypatch.setattr(t, "Emitter", FakeEmitter)
    state = {name: SimpleNamespace(value=0) for name in t.STATE_FIELDS}
    state["worker_exitcode"].value = t.NO_EXIT
    s = t.Session(10, 11, state)

    def factory(emitter, pid):
        calls = []
        constructed.append((emitter, pid, calls))

        def observe(site, locals_):
            calls.append((site, locals_))
            return emitter.emit({"site": site, "pid": pid})
        return observe

    s.install_observer(factory)
    return s, current, closes, forks, constructed


def child(session):
    s, current, _, _, _ = session
    s._before_fork()
    current.update(pid=200, ppid=100)
    s._after_child()
    return s


def good_state():
    values = {name: 0 for name in t.STATE_FIELDS}
    values.update(parent_pid=100, worker_pid=200, expected_worker_pid=200,
                  worker_parent_pid=100, fork_attempts=1, worker_exitcode=0)
    return values


def test_runtime_boundary_refuses_nonqualified_without_side_effects(monkeypatch):
    monkeypatch.setattr(t, "_runtime_supported", lambda method: False)
    monkeypatch.setattr(t.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    assert t.capture_native_pair("absent.py", "bad", {})["status"] == "UNSUPPORTED"


def test_parent_callback_is_constructed_before_fork(session):
    s, _, _, forks, constructed = session
    assert len(forks) == 1
    assert set(forks[0]) == {"before", "after_in_parent", "after_in_child"}
    assert constructed[0][1] == 100
    s.observe("accepted", {"i": 0})
    assert s.emitter.events == [{"site": "accepted", "pid": 100}]


def test_child_owns_fresh_identity_sequence_and_descriptor(session):
    s, _, closes, _, constructed = session
    s.observe("parent", {})
    parent_emitter = s.emitter
    s = child(session)
    assert s.emitter is not parent_emitter
    assert s.emitter.producer == 200
    assert s.emitter.attempted == 0
    assert closes == [10]
    assert s.parent_fd is None and s.worker_fd == 11
    assert [item[1] for item in constructed] == [100, 200]
    s.observe("commit", {"i": 0})
    assert parent_emitter.attempted == 1
    assert s.emitter.events == [{"site": "commit", "pid": 200}]


def test_parent_closes_inherited_child_writer(session):
    s, _, closes, _, _ = session
    s._before_fork()
    s._after_parent()
    assert closes == [11]
    assert s.worker_fd is None


def test_extra_fork_poisoned_and_never_inherits_emitter_as_child(session):
    s, current, closes, _, _ = session
    s._before_fork()
    s._before_fork()
    current.update(pid=300, ppid=100)
    s._after_child()
    assert s.state["unexpected_fork"].value == 1
    assert s.observer is None
    assert closes == [10, 11]
    assert not s.observe("commit", {})


def test_atfork_factory_failure_is_visible_without_aborting_native_child(session):
    s, current, _, _, _ = session
    s.factory = lambda *a: (_ for _ in ()).throw(ValueError("fixture"))
    s._before_fork()
    current.update(pid=200, ppid=100)
    s._after_child()
    assert s.state["observer_error"].value == 1
    assert s.observer is None


def test_child_lifecycle_preserves_normal_return_and_counts(session):
    s = child(session)
    with s.lifecycle("worker", "unsafe_execute", {}):
        s.observe("commit", {"i": 0})
    assert s.emitter.sealed
    assert s.worker_fd is None
    assert s.state["worker_entered"].value == 1
    assert s.state["worker_finished"].value == 1
    assert s.state["worker_normal"].value == 1
    assert s.state["worker_attempted"].value == 3
    assert [e.get("event") for e in s.emitter.events] == ["enter", None, "return"]


@pytest.mark.parametrize("exception", [ValueError("native"), TimeoutError(), KeyboardInterrupt()])
def test_lifecycle_never_suppresses_or_replaces_native_exception(session, exception):
    s = child(session)
    with pytest.raises(type(exception)) as raised:
        with s.lifecycle("worker", "unsafe_execute", {}):
            raise exception
    assert raised.value is exception
    assert s.state["worker_normal"].value == 0
    assert s.emitter.events[-1]["exception"] == type(exception).__name__
    assert s.emitter.events[-1]["event"] == "raise"


def test_nested_or_duplicate_worker_lifecycle_is_not_complete_evidence(session):
    s = child(session)
    s.worker_enter()
    assert not s.worker_enter()
    assert s.state["observer_error"].value == 1


def test_wrong_role_lifecycle_refused_before_use(session):
    s, *_ = session
    with pytest.raises(t.UnsupportedTransport):
        s.lifecycle("unknown", "unsafe_execute", {})


def test_copied_parent_producer_is_not_accepted(session):
    s = child(session)
    s.emitter.producer = 100
    assert not s.observe("commit", {})
    assert s.state["observer_error"].value == 1


def test_only_declared_start_site_intercepts_process(session, monkeypatch):
    s, *_ = session
    seen = []
    monkeypatch.setattr(s, "child_started", lambda p: seen.append(p))
    process = object()
    s.observe("some-other-site", {"p": process})
    assert not seen
    s.observe("native-child-started", {"p": process})
    assert seen == [process]


def test_missing_start_process_is_acquisition_failure(session):
    s, *_ = session
    s.observe("native-child-started", {})
    assert s.state["fork_error"].value == 1


def test_process_properties_are_not_executed():
    class Candidate:
        @property
        def pid(self):
            pytest.fail("candidate property executed")
    with pytest.raises(t.UnsupportedTransport):
        t.native_process_snapshot(Candidate())


def test_exact_process_cached_state_read_without_poll(monkeypatch):
    class Process:
        pass
    class Popen:
        def poll(self):
            pytest.fail("poll changes native lifecycle")
    process, popen = Process(), Popen()
    popen.pid, popen.returncode = 200, None
    process._popen, process._parent_pid = popen, 100
    monkeypatch.setattr(t, "_process_types", lambda: (Process,))
    monkeypatch.setattr(t, "_popen_type", lambda: Popen)
    assert t.native_process_snapshot(process) == {
        "pid": 200, "parent_pid": 100, "exitcode": None}
    popen.returncode = -9
    assert t.native_process_snapshot(process)["exitcode"] == -9


@pytest.mark.parametrize("field,value", [
    ("pid", True), ("pid", 0), ("pid", "200"), ("returncode", False), ("returncode", "0"),
])
def test_process_cached_fields_require_exact_types(monkeypatch, field, value):
    class Process:
        pass
    class Popen:
        pass
    process, popen = Process(), Popen()
    popen.pid, popen.returncode = 200, 0
    setattr(popen, field, value)
    process._popen, process._parent_pid = popen, 100
    monkeypatch.setattr(t, "_process_types", lambda: (Process,))
    monkeypatch.setattr(t, "_popen_type", lambda: Popen)
    with pytest.raises(t.UnsupportedTransport):
        t.native_process_snapshot(process)


def test_native_child_start_linkage_and_repeat_refusal(session, monkeypatch):
    s, *_ = session
    monkeypatch.setattr(t, "native_process_snapshot", lambda p: {
        "pid": 200, "parent_pid": 100, "exitcode": None})
    assert s.child_started(object())
    assert s.state["expected_worker_pid"].value == 200
    assert not s.child_started(object())
    assert s.state["fork_error"].value == 1


@pytest.mark.parametrize("changes,reason", [
    ({"worker_pid": 201}, "native_child_identity"),
    ({"expected_worker_pid": 0}, "native_child_identity"),
    ({"worker_parent_pid": 99}, "native_parent_identity"),
    ({"fork_attempts": 2}, "fork_inventory"),
    ({"parent_pid": 99}, "parent_identity"),
    ({"observer_error": 1}, "observer_error"),
    ({"unexpected_fork": 1}, "unexpected_fork"),
    ({"fork_error": 1}, "fork_error"),
    ({"worker_close_error": 1}, "worker_close_error"),
])
def test_graph_rejects_independent_identity_or_route_failure(changes, reason):
    receipt = t.graph_receipt({**good_state(), **changes}, 100)
    assert not receipt["intact"]
    assert reason in receipt["errors"]


def test_graph_accepts_only_matched_parent_and_actual_native_child():
    receipt = t.graph_receipt(good_state(), 100)
    assert receipt["intact"] and receipt["worker_required"]
    assert receipt["worker_pid"] == receipt["expected_worker_pid"] == 200


def test_preflight_without_child_does_not_invent_missing_child():
    state = {name: 0 for name in t.STATE_FIELDS}
    state["parent_pid"] = 100
    receipt = t.graph_receipt(state, 100)
    assert receipt["intact"]
    assert not receipt["worker_required"]


@pytest.mark.parametrize("value", [True, 0, -1, 61, float("nan")])
def test_bad_wall_budget_refused_without_spawn(monkeypatch, value):
    monkeypatch.setattr(t, "_runtime_supported", lambda method: True)
    with pytest.raises(InvalidEvidence):
        t.capture_native_pair("absent.py", "bad", {}, wall_seconds=value)


InvalidEvidence = t.InvalidEvidence


def test_process_admission_does_not_execute_hostile_metaclass_equality():
    class Meta(type):
        def __eq__(cls, other):
            pytest.fail("metaclass equality executed")
    class Hostile(metaclass=Meta):
        pass
    with pytest.raises(t.UnsupportedTransport):
        t.native_process_snapshot(Hostile())


def test_exception_name_does_not_execute_metaclass_override(session):
    class Meta(type):
        def __getattribute__(cls, name):
            if name == "__name__":
                raise AssertionError("candidate metaclass name override executed")
            return type.__getattribute__(cls, name)
    class NativeException(Exception, metaclass=Meta):
        pass
    s = child(session)
    native = NativeException()
    try:
        with s.lifecycle("worker", "unsafe_execute", {}):
            raise native
    except NativeException as caught:
        assert caught is native
    else:
        pytest.fail("native exception suppressed")
    assert s.emitter.events[-1]["exception"] == "NativeException"


@pytest.mark.parametrize("failure", ["setup", "drain"])
def test_every_poststart_setup_or_drain_failure_cleans_group_and_fds(tmp_path, monkeypatch, failure):
    adapter = tmp_path / "adapter.py"
    adapter.write_text("def run(session, argument): return None")
    closed, killed, joined = [], [], []
    proc = SimpleNamespace(pid=200, start=lambda: None, join=lambda n: joined.append(n),
                           is_alive=lambda: False)
    ctx = SimpleNamespace(
        RawValue=lambda *args: SimpleNamespace(value=args[-1]),
        RawArray=lambda typ, length: bytearray(length),
        Process=lambda **kwargs: proc,
    )
    pairs = iter(((10, 11), (12, 13)))
    monkeypatch.setattr(t, "_runtime_supported", lambda method: True)
    monkeypatch.setattr(t.mp, "get_context", lambda method: ctx)
    monkeypatch.setattr(t.os, "pipe2", lambda flags: next(pairs), raising=False)
    monkeypatch.setattr(t.os, "O_NONBLOCK", 0, raising=False)
    monkeypatch.setattr(t.os, "O_CLOEXEC", 0, raising=False)
    monkeypatch.setattr(t.os, "fpathconf", lambda *args: 4096, raising=False)
    monkeypatch.setattr(t, "_close", closed.append)
    monkeypatch.setattr(t, "_terminate_group", lambda pid: killed.append(pid))
    if failure == "setup":
        monkeypatch.setattr(t.selectors, "DefaultSelector",
                            lambda: (_ for _ in ()).throw(RuntimeError("selector setup")))
    else:
        monkeypatch.setattr(t, "_collect_started",
                            lambda *a: (_ for _ in ()).throw(RuntimeError("drain")))
    request = dict(adapter=str(adapter), adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
                   start_method="fork", max_trace_bytes=8192, wall_seconds=1,
                   argument={}, group_receipt=str(tmp_path / "group.txt"))
    with pytest.raises(RuntimeError):
        t.acquire(request)
    assert killed == [200]
    assert joined == [3]
    assert sorted(closed) == [10, 11, 12, 13]


@pytest.mark.parametrize("failure", ["nonzero", "missing", "malformed", "bad-schema"])
def test_all_supervisor_failures_clean_recorded_native_group(tmp_path, monkeypatch, failure):
    adapter = tmp_path / "adapter.py"
    adapter.write_text("def run(session, argument): return None")
    cleaned = []
    monkeypatch.setattr(t, "_runtime_supported", lambda method: True)
    monkeypatch.setattr(t, "_terminate_group", lambda pid: cleaned.append(pid) or "SIGKILL")

    class Process:
        pid = 100

        def __init__(self, command, **kwargs):
            self.request = json.loads(Path(command[-2]).read_bytes())
            self.output = Path(command[-1])

        def wait(self, **kwargs):
            Path(self.request["group_receipt"]).write_text(json.dumps({"pid":200,"starttime":123}), encoding="ascii")
            if failure == "malformed":
                self.output.write_text("{invalid")
            elif failure == "bad-schema":
                self.output.write_text('{"schema":"wrong","status":"CAPTURED"}')
            return 7 if failure == "nonzero" else 0

    monkeypatch.setattr(t.subprocess, "Popen", Process)
    receipt = t.capture_native_pair(adapter, hashlib.sha256(adapter.read_bytes()).hexdigest(), {})
    assert receipt["status"] == "INCOMPLETE"
    assert receipt["failure_cleanup"] == {"group_pid": 200, "action": "SIGKILL", "recorded_starttime":123, "direct_pid_fallback":None, "group_retry":None}
    assert cleaned == [200]


@pytest.mark.parametrize("value", ["0", "-1", "1\n", "bad", "1" * 40])
def test_invalid_cleanup_group_receipt_never_targets_a_group(tmp_path, monkeypatch, value):
    target = tmp_path / "group.txt"
    target.write_text(value)
    monkeypatch.setattr(t, "_terminate_group", lambda pid: pytest.fail("invalid kill target"))
    assert t._cleanup_recorded_group(target)["action"] == "invalid_group_receipt"


def test_wall_budget_type_check_never_dispatches_metaclass_equality(monkeypatch):
    class Meta(type):
        def __eq__(cls, other):
            pytest.fail("metaclass equality executed")
    class Value(metaclass=Meta):
        pass
    monkeypatch.setattr(t, "_runtime_supported", lambda method: True)
    with pytest.raises(InvalidEvidence):
        t.capture_native_pair("absent.py", "bad", {}, wall_seconds=Value())


def test_buffer_identity_rejects_candidate_property_without_dispatch():
    class Candidate:
        @property
        def _obj(self):
            pytest.fail("candidate property executed")
    with pytest.raises(t.PrimitiveError):
        t.native_buffer_snapshot({"details": Candidate()}, ("details",))


@pytest.mark.parametrize("same", [True, False])
def test_buffer_linkage_requires_same_actual_identity_pair(same):
    original = {"details": {"wrapper": 10, "backing": 11, "address": 12, "bytes": 2}}
    other = original if same else {"details": {"wrapper": 20, "backing": 21, "address": 22, "bytes": 2}}
    def packet(event, value):
        return {"event": {"schema": "zerorun-acquisition-lifecycle/1", "event": event, "buffers": value}}
    receipt = t.buffer_linkage({
        "parent": {"events": [packet("child_started", original)]},
        "worker": {"events": [packet("enter", other)]},
    })
    assert receipt["required"]
    assert receipt["matched"] is same


@pytest.mark.parametrize("identity", [123, 124, None])
def test_outer_cleanup_only_falls_back_to_verified_live_owned_pid(tmp_path, monkeypatch, identity):
    path = tmp_path / "group.json"
    path.write_text(json.dumps({"pid":200,"starttime":123}))
    killed = []
    groups = []
    monkeypatch.setattr(t, "_linux_process_identity", lambda pid: identity)
    monkeypatch.setattr(t, "_terminate_group", lambda pid: groups.append(pid) or "already_absent")
    monkeypatch.setattr(t.os, "pidfd_open", lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(t.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(t.signal, "pidfd_send_signal", lambda fd, signal: killed.append(fd - 1), raising=False)
    monkeypatch.setattr(t.os, "close", lambda fd: None)
    receipt = t._cleanup_recorded_group(path)
    assert killed == ([200] if identity == 123 else [])
    assert groups == ([200,200] if identity == 123 else [200] if identity is None else [])
    assert receipt["direct_pid_fallback"] == ("matching_owned_PID_SIGKILL" if identity == 123 else None)


def test_recycled_live_leader_is_rejected_before_any_process_group_signal(tmp_path,monkeypatch):
    path=tmp_path/'group.json'
    path.write_text(json.dumps({'pid':200,'starttime':123}))
    groups=[]
    monkeypatch.setattr(t,'_linux_process_identity',lambda pid:124)
    monkeypatch.setattr(t,'_terminate_group',lambda pid:groups.append(pid) or 'SIGKILL')
    receipt=t._cleanup_recorded_group(path)
    assert groups==[]
    assert receipt['action']=='live_process_identity_mismatch'


def test_dead_leader_does_not_hide_remaining_recorded_group(tmp_path,monkeypatch):
    path=tmp_path/'group.json'
    path.write_text(json.dumps({'pid':200,'starttime':123}))
    groups=[]
    monkeypatch.setattr(t,'_linux_process_identity',lambda pid:None)
    monkeypatch.setattr(t,'_terminate_group',lambda pid:groups.append(pid) or 'SIGKILL')
    receipt=t._cleanup_recorded_group(path)
    assert groups==[200]
    assert receipt['action']=='SIGKILL'


def path_adapter_module():
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'validation/evalplus_path/adapter.py'
    spec=importlib.util.spec_from_file_location('_test_path_adapter',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_case(count):
    return dict(id='bank',code='def check(x): return x',inputs=[[i] for i in range(count)],
                expected=list(range(count)),entry='check',atol=0,fast=False)


def test_pinned_native_case_file_supports_128_inputs_without_wire_containers(tmp_path):
    path=tmp_path/'native.json'
    case=native_case(128)
    path.write_text(json.dumps(case))
    argument={'case_path':str(path),'case_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    t.primitives(argument)
    assert path_adapter_module().read_case(argument)==case
    with pytest.raises(t.PrimitiveError):
        t.primitives({'case':case})


@pytest.mark.parametrize('defect',['hash','duplicate','nonfinite','shape'])
def test_pinned_native_case_file_refuses_untrusted_metadata(tmp_path,defect):
    path=tmp_path/'native.json'
    content=json.dumps(native_case(128))
    if defect=='duplicate': content='{"id":"a","id":"b"}'
    if defect=='nonfinite': content='{"value":NaN}'
    if defect=='shape': content='[]'
    path.write_text(content)
    expected=hashlib.sha256(path.read_bytes()).hexdigest() if defect!='hash' else '0'*64
    with pytest.raises(t.UnsupportedTransport):
        path_adapter_module().read_case({'case_path':str(path),'case_sha256':expected})


@pytest.mark.parametrize('count,trace,allowed',[(128,16*1024*1024,True),(1000,16*1024*1024,True),
                                            (4097,16*1024*1024,False),(3000,16*1024*1024,False),
                                            (128,8192,False)])
def test_native_file_route_checks_declared_inventory_event_and_trace_bounds(count,trace,allowed):
    p={'facts':{'progress':{'raw':'int'},'parent':{'raw':'str'}},'sites':{
        'progress-write':{'kind':'progress','producer_role':'worker','projection':{'raw':{'local':'progress'}}},
        'parent-return':{'kind':'parent','producer_role':'parent','projection':{'raw':{'local':'stat'}}}}}
    module=path_adapter_module()
    if allowed:
        result=module.native_budget(p,{'sha256':'0'*64},native_case(count),'test',trace)
        assert result['inputs']==count and result['semantic_events_upper']<=16384
    else:
        with pytest.raises(t.UnsupportedTransport):
            module.native_budget(p,{'sha256':'0'*64},native_case(count),'test',trace)
