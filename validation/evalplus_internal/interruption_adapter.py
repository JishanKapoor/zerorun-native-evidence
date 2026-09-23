"""Retain actual native function entry before deliberately interrupting it."""


def run(emitter, argument):
    import importlib.util
    import os
    from pathlib import Path
    import sys

    path = Path(__file__).with_name("adapter.py")
    spec = importlib.util.spec_from_file_location("_evalplus_qualified_adapter", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    entered = False

    def trace(frame, event, value):
        nonlocal entered
        if not entered and event == "call" and frame.f_code.co_name == "unsafe_execute" and frame.f_code.co_filename.endswith("evalplus/eval/__init__.py"):
            entered = True
            # This is a raw acquisition probe, not a semantic policy observation.
            emitter.emit(dict(probe="actual_native_unsafe_execute_entry", producer=os.getpid()))
            sys.settrace(None)
        return trace

    sys.settrace(trace)
    return adapter.run(emitter, argument)
