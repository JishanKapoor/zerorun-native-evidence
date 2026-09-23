"""One real authored pytest run, with retained stdout/stderr and native hook log."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import NativeReference, load_native, source_inventory


def run(args):
    # Block ambient plugins/configuration from silently changing the fixture.
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.environ.pop('PYTEST_ADDOPTS', None)
    expected = json.loads(Path(args.source_manifest).read_text(encoding='utf-8'))
    pytest, finder = load_native(expected)
    work = Path(args.work).resolve()
    reference = NativeReference(args.reference, run=args.run, attempt=args.attempt)
    try:
        code = pytest.main(['-c', str(work / 'pytest.ini'), '--confcutdir', str(work),
            '-p', 'no:cacheprovider', '-o', 'addopts=', '-rA', '-vv', '--tb=short', '--color=no',
            str(work / 'test_native_controls.py')], plugins=[reference])
        if source_inventory() != expected:
            raise ValueError('Native pytest bytes changed during execution')
        return int(code)
    finally:
        sys.meta_path.remove(finder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--attempt', type=int, required=True)
    raise SystemExit(run(parser.parse_args()))
