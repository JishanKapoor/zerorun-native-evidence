"""Unmodified native parent deadline reference; no production framework import."""

import hashlib
import importlib
import json
from pathlib import Path
import sys


def run(root, prepared, case, output):
    dependencies = json.loads((prepared / "native-dependencies.json").read_text())
    assert all(hashlib.sha256((root / path).read_bytes()).hexdigest() == expected for path, expected in dependencies.items())
    sys.path.insert(0, str(root))
    native = importlib.import_module("evalplus.eval")
    source = (prepared / "native.py").read_bytes().decode("utf-8")
    exec(compile(source, native.__file__, "exec"), native.__dict__)
    snapshots = []

    def trace(frame, event, value):
        if frame.f_code is not native.untrusted_check.__code__:
            return None
        if event == "return" and type(value) is tuple:
            snapshots.append(dict(identity=dict(run="exposed-native-worker", candidate=case["id"], obligation=0, phase="base", attempt=1), values=dict(raw=value[0], details_json=json.dumps(value[1], separators=(",", ":")), progress=int(frame.f_locals["progress"].value))))
        return trace

    sys.settrace(trace)
    grade, details = native.untrusted_check("humaneval", case["code"], case["inputs"], case["entry"], case["expected"], case["atol"], [0.001], fast_check=False, min_time_limit=0.08, gt_time_limit_factor=4)
    sys.settrace(None)
    assert len(snapshots) == 1
    with output.open("x", encoding="utf-8") as stream:
        json.dump(dict(parent=dict(grade=grade, details=[int(v) for v in details]), facts=snapshots, framework_semantics_imported=any(name == "zerorun_harness" or name.startswith("zerorun_harness.") for name in sys.modules)), stream, indent=2)


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), json.loads(Path(sys.argv[3]).read_text())["case"], Path(sys.argv[4]))
