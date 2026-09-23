"""Bound original upstream package under the common observation recorder."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def run(emitter, options):
    sys.path.insert(0, str(Path(__file__).parent))
    from native_driver import load_native, run_case
    from zerorun_harness.binding import recorder
    fixture = Path(options["fixture_root"]) / options["version"]
    profile = json.loads((fixture / "profile.json").read_text())
    binding = json.loads((fixture / "binding.json").read_text())
    hashes = json.loads((fixture / "source-hashes.json").read_text())
    callback = recorder(profile, binding, emitter, os.getpid(),
                        context=dict(run=options["run"], candidate="authored-reporting"))
    native = load_native(options["native_root"], hashes, binding["transformed"], callback)
    result = run_case(native, options["case"], options["run"], options["work"], options["call_journal"])
    if Path(options["work"]).exists():
        shutil.copytree(options["work"], options["retained_work"])
    raw = json.dumps(result, indent=2).encode("utf-8")
    with Path(options["native_output"]).open("xb") as stream:
        stream.write(raw)
    # Full original results stay in the retained artifact, outside the bounded
    # control-plane result. This digest is not an expected semantic outcome.
    return dict(output_sha256=hashlib.sha256(raw).hexdigest(), operations=len(result["operations"]))
