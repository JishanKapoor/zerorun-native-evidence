"""Mechanically bound original Inspect eval in a fresh acquisition child."""
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
    from zerorun_harness.records import register_records
    fixtures = Path(options['fixture_root'])
    profile = json.loads((fixtures / 'profile.json').read_text())
    binding = json.loads((fixtures / 'binding.json').read_text())
    hashes = json.loads((fixtures / 'source-hashes.json').read_text())
    box = {}

    def dispatch(site, state):
        return box['callback'](site, state)

    dispatch.enter = lambda function: box['callback'].enter(function)
    native = load_native(options['native_root'], hashes, binding['transformed'], dispatch)
    metric = native[1]
    records = register_records(profile, binding, {'score': metric.Score, 'sample_score': metric.SampleScore})
    box['callback'] = recorder(profile, binding, emitter, os.getpid(), records=records,
        context=dict(run=options['run'], candidate='authored-inspect'))
    result = run_case(native, options['case'], options['work'], options['call_journal'])
    shutil.copytree(options['work'], options['retained_work'])
    raw = json.dumps(result, indent=2, allow_nan=False).encode('utf-8')
    with Path(options['native_output']).open('xb') as stream:
        stream.write(raw)
    return dict(output_sha256=hashlib.sha256(raw).hexdigest(), native_calls=result['native_calls'])
