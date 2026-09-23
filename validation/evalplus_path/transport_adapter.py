"""Authored process controls, not EvalPlus candidates or historical cases."""

import multiprocessing as mp
import os
import time

SESSION = None


def worker(mode, details=None, progress=None):
    with SESSION.lifecycle("worker", "worker", locals()):
        SESSION.observe("worker-entered-control", {"value": 1})
        if mode == "raise":
            raise ValueError("authored process lifecycle control")
        if mode == "abrupt":
            os._exit(0)
        if mode == "killed":
            time.sleep(10)
        if mode == "closed-worker-channel":
            os.close(SESSION.emitter.fd)
        if mode == "flood":
            for index in range(5000):
                SESSION.observe("worker-control", {"value": index})
        SESSION.observe("worker-control", {"value": 2})


def run(session, argument):
    global SESSION
    SESSION = session

    def factory(emitter, pid):
        def observe(site, state):
            return emitter.emit({"site": site, "pid": pid, "value": state.get("value", 0)})
        return observe

    mode = argument["mode"]
    use_buffers = mode in ("buffer-positive", "buffer-mismatch")
    session.install_observer(factory, buffer_locals=("details", "progress") if use_buffers else ())
    if mode == "preflight":
        raise TypeError("authored preflight before native child")
    details, progress = mp.Array("b", [0, 0]), mp.Value("i", 0)
    child_details = mp.Array("b", [0, 0]) if mode == "buffer-mismatch" else details
    process = mp.Process(target=worker, args=(mode, child_details, progress))
    process.start()
    session.observe("native-child-started", {"p": process, "details": details, "progress": progress})
    process.join(0.15 if mode == "killed" else 4)
    if process.is_alive():
        process.kill()
        process.join(2)
    first_exitcode = process.exitcode
    if mode == "extra-child":
        second = mp.Process(target=worker, args=("normal",))
        second.start()
        session.observe("native-child-started", {"p": second})
        second.join(2)
    session.observe("parent-return-control", {"value": 3})
    return {"first_child_exitcode": first_exitcode}
