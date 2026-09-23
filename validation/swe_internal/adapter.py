"""A4 adapter: common projections execute inside original native functions."""
import json
import os
from pathlib import Path
import sys


def run(emitter, options):
    directory = Path(options["fixture_root"])
    sys.path.insert(0, str(Path(__file__).parent))
    from native_driver import load_native, invoke
    from zerorun_harness.binding import recorder
    fixture = directory / options["version"]
    profile = json.loads((fixture / "profile.json").read_text())
    binding = json.loads((fixture / "binding.json").read_text())
    hashes = json.loads((fixture / "source-hashes.json").read_text())
    callback = recorder(profile, binding, emitter, os.getpid(),
                        context={"run": options["run"], "candidate": "authored-control"})
    native = load_native(options["native_root"], hashes, binding["transformed"], callback)
    return invoke(native, options["case"], options["work"])
