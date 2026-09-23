"""Freeze authored fixture and installed native pytest source bytes, zero calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import TEST_SOURCE, EXPECTED
from native import source_inventory


def prepare(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'test_native_controls.py').write_text(TEST_SOURCE, encoding='utf-8', newline='\n')
    (output / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
    for name in ('entry.py', 'native.py'):
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    manifest = source_inventory()
    if manifest['version'] != '8.4.2':
        raise ValueError('Only native pytest 8.4.2 is declared')
    (output / 'native-source.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    design = dict(schema='s8-native-pytest-phase-design/1', native_version='8.4.2',
        expected=EXPECTED, planned_pytest_calls=2, acquisition_attempts=[1, 2],
        scope='Two separate authored subprocess executions; not upstream retry or benchmark patch evaluation',
        raw_log='Unedited pytest stdout/stderr retained; any SWE acquisition markers stored in a separate artifact',
        source_files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(output.iterdir()) if p.is_file()})
    (output / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    return design


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), indent=2))
