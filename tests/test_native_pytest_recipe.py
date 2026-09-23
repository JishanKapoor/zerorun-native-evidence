import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parents[1] / 'validation/pytest_native'


def module(name):
    spec = importlib.util.spec_from_file_location('native_pytest_test_' + name, HERE / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_fixed_fixture_and_declared_actual_phase_population():
    fixtures = module('fixtures')
    tree = ast.parse(fixtures.TEST_SOURCE)
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}
    assert {name.split('[')[0] for name in fixtures.EXPECTED} == names
    assert sum(map(len, fixtures.EXPECTED.values())) == 28
    assert fixtures.EXPECTED['test_setup_error'] == [('setup', 'failed'), ('teardown', 'passed')]
    assert fixtures.EXPECTED['test_teardown_error'][-1] == ('teardown', 'failed')


def test_native_hook_keeps_xfail_separate_from_skipped_and_each_attempt(tmp_path):
    from _pytest.reports import TestReport
    helper = module('native')
    for attempt in (1, 2):
        path = tmp_path / (str(attempt) + '.jsonl')
        reference = helper.NativeReference(path, run='authored', attempt=attempt)
        reference.pytest_sessionstart(None)
        report = TestReport('test_native_controls.py::test_xfail', ('test_native_controls.py', 1, ''),
                            {}, 'skipped', None, 'call', wasxfail='explicit expected failure')
        reference.pytest_runtest_logreport(report)
        reference.pytest_sessionfinish(None, 1)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert records[1] == dict(event='test_report', sequence=2, run='authored', attempt=attempt,
            nodeid='test_native_controls.py::test_xfail', when='call', outcome='skipped',
            wasxfail='explicit expected failure')
        assert records[2]['exitstatus'] == 1


@pytest.mark.parametrize('field,value', [('when', 'retry'), ('outcome', 'PASS'), ('nodeid', 42), ('wasxfail', True)])
def test_native_hook_refuses_unqualified_report_fields(tmp_path, field, value):
    from _pytest.reports import TestReport
    helper = module('native')
    reference = helper.NativeReference(tmp_path / 'reference.jsonl', run='authored', attempt=1)
    report = TestReport('x', ('x', 1, ''), {}, 'passed', None, 'call')
    report.__dict__[field] = value
    with pytest.raises(ValueError):
        reference.pytest_runtest_logreport(report)
    assert reference.output.read_text() == ''


def test_reference_preserves_duplicate_native_occurrences(tmp_path):
    from _pytest.reports import TestReport
    reference = module('native').NativeReference(tmp_path / 'reference.jsonl', run='authored', attempt=1)
    report = TestReport('x', ('x', 1, ''), {}, 'passed', None, 'call')
    reference.pytest_runtest_logreport(report)
    reference.pytest_runtest_logreport(report)
    rows = [json.loads(line) for line in reference.output.read_text().splitlines()]
    assert len(rows) == 2 and [row['sequence'] for row in rows] == [1, 2]


def test_native_reference_never_overwrites_prior_attempt(tmp_path):
    helper = module('native')
    path = tmp_path / 'reference.jsonl'
    helper.NativeReference(path, run='authored', attempt=1)
    with pytest.raises(FileExistsError):
        helper.NativeReference(path, run='authored', attempt=1)


@pytest.mark.parametrize('corrupt', [False, True])
def test_fresh_native_import_checks_pin_and_keeps_lazy_import_verification(tmp_path, corrupt):
    pin = module('native').source_inventory()
    if corrupt:
        pin['files']['_pytest/terminal.py'] = '0' * 64
    path = tmp_path / 'pin.json'
    path.write_text(json.dumps(pin))
    script = '''import json,sys
sys.path.insert(0,sys.argv[1])
from native import load_native
native,finder=load_native(json.load(open(sys.argv[2])))
assert finder in sys.meta_path
import _pytest.junitxml
assert finder in sys.meta_path
sys.meta_path.remove(finder)
print(native.__version__)
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(HERE), str(path)],
                            capture_output=True, text=True, timeout=30)
    if corrupt:
        assert result.returncode != 0 and 'source inventory mismatch' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == '8.4.2'
