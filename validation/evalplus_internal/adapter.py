"""One actual worker or parent per A4 capture; no cross-process impersonation."""


def run(emitter, argument):
    import hashlib
    import importlib
    import json
    import multiprocessing
    import os
    from pathlib import Path
    import sys
    from zerorun_harness.binding import recorder, validate_binding

    root = Path(argument["prepared"])
    profile = json.loads((root / "profile.json").read_text())
    binding = json.loads((root / "binding.json").read_text())
    case = argument["case"]
    validate_binding(profile, binding)
    dependencies = json.loads((root / "native-dependencies.json").read_text())
    for path, expected_sha in dependencies.items():
        if hashlib.sha256((Path(argument["native_root"]) / path).read_bytes()).hexdigest() != expected_sha:
            raise ValueError("Pinned native dependency changed: " + path)
    sys.path.insert(0, argument["native_root"])
    native = importlib.import_module("evalplus.eval")
    original = binding["original"]["evalplus/eval/__init__.py"]
    exec(compile(original, native.__file__, "exec"), native.__dict__)
    original_worker = native.unsafe_execute
    callback = recorder(profile, binding, emitter, os.getpid(), context=dict(run="exposed-native-worker", candidate=case["id"], phase="base", attempt=1))
    native.__dict__["__zr_observe"] = callback
    exec(compile(binding["transformed"]["evalplus/eval/__init__.py"], native.__file__, "exec"), native.__dict__)
    if argument["mode"] == "parent":
        # The worker remains original in this separate acquisition. A4's channel
        # contains only this parent's facts; no inherited emitter is used.
        native.unsafe_execute = original_worker
        grade, details = native.untrusted_check(dataset="humaneval", code=case["code"], inputs=case["inputs"], entry_point=case["entry"], expected=case["expected"], atol=case["atol"], ref_time=["invalid"] if case.get("preflight_error") else [0.001] * len(case["inputs"]), fast_check=case["fast"], min_time_limit=0.08, gt_time_limit_factor=4)
        return dict(grade=grade, details=[int(v) for v in details])
    stat = multiprocessing.Value("i", native._UNKNOWN)
    details = multiprocessing.Array("b", [False] * len(case["inputs"]))
    progress = multiprocessing.Value("i", 0)
    native.unsafe_execute("humaneval", case["entry"], case["code"], case["inputs"], case["expected"], [0.08] * len(case["inputs"]), case["atol"], case["fast"], stat, details, progress)
    return dict(stat=int(stat.value), details=[int(v) for v in details], progress=int(progress.value))
