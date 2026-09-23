"""Verified original pytest loading and independent public native-hook facts.

No production observer, identity mapper, policy interpreter or verdict imports.
The exact source loader remains installed for lazy native imports until closed.
"""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys


def source_inventory():
    result = {}
    for name in ('_pytest', 'pytest'):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin:
            raise ValueError('Native pytest package is unavailable')
        root = Path(spec.origin).resolve().parent
        for path in sorted(root.rglob('*.py')):
            result[name + '/' + path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(version=importlib.metadata.version('pytest'), files=result)


def load_native(expected, transformed=None, observe=None):
    if any(name in ('_pytest', 'pytest') or name.startswith(('_pytest.', 'pytest.')) for name in sys.modules):
        raise ValueError('pytest qualification needs a fresh interpreter')
    if expected.get('version') != '8.4.2' or source_inventory() != expected:
        raise ValueError('Original pytest source inventory mismatch')
    roots = {name: Path(importlib.util.find_spec(name).origin).resolve().parent for name in ('_pytest', 'pytest')}
    transformed = {} if transformed is None else transformed
    if not set(transformed).issubset(expected['files']):
        raise ValueError('Transformed pytest source outside pinned package')

    class VerifiedLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            name = fullname.split('.')[0]
            relative = name + '/' + Path(self.path).resolve().relative_to(roots[name]).as_posix()
            raw = Path(self.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected['files'].get(relative):
                raise ValueError('Native pytest source changed during import')
            return compile(transformed.get(relative, raw), self.path, 'exec')

        def exec_module(self, module):
            name = module.__name__.split('.')[0]
            relative = name + '/' + Path(self.path).resolve().relative_to(roots[name]).as_posix()
            if relative in transformed:
                if observe is None:
                    raise ValueError('Bound native pytest source needs its callback')
                module.__dict__['__zr_observe'] = observe
                module.__dict__['__zr_observe__'] = observe
            super().exec_module(module)

    class VerifiedFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            name = fullname.split('.')[0]
            if name not in roots:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or not spec.origin:
                raise ImportError('Unresolved original pytest module: ' + fullname)
            relative = name + '/' + Path(spec.origin).resolve().relative_to(roots[name]).as_posix()
            if relative not in expected['files']:
                raise ImportError('Unpinned pytest module: ' + fullname)
            spec.loader = VerifiedLoader(fullname, spec.origin)
            return spec

    finder = VerifiedFinder()
    sys.meta_path.insert(0, finder)
    try:
        native = importlib.import_module('pytest')
    except BaseException:
        sys.meta_path.remove(finder)
        raise
    return native, finder


class NativeReference:
    """Read actual TestReport primitive storage at the public pytest hook."""
    def __init__(self, output, *, run, attempt):
        if type(run) is not str or not run or type(attempt) is not int or attempt < 1:
            raise ValueError('Explicit acquisition run and attempt required')
        self.output = Path(output)
        self.run, self.attempt = run, attempt
        self.sequence = 0
        self.output.open('x', encoding='utf-8').close()

    def append(self, event, **values):
        self.sequence += 1
        row = dict(event=event, sequence=self.sequence, run=self.run, attempt=self.attempt, **values)
        with self.output.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')

    def pytest_sessionstart(self, session):
        self.append('session_start')

    def pytest_runtest_logreport(self, report):
        from _pytest.reports import TestReport
        if type(report) is not TestReport:
            raise ValueError('Unexpected native report class')
        data = object.__getattribute__(report, '__dict__')
        values = {field: data[field] for field in ('nodeid', 'when', 'outcome')}
        if any(type(value) is not str for value in values.values()):
            raise ValueError('Native report primitive field mismatch')
        if values['when'] not in ('setup', 'call', 'teardown') or values['outcome'] not in ('passed', 'failed', 'skipped'):
            raise ValueError('Undeclared native report phase/outcome')
        xfail = data.get('wasxfail')
        if xfail is not None and type(xfail) is not str:
            raise ValueError('Unexpected native expected-failure metadata')
        self.append('test_report', **values, wasxfail=xfail)

    def pytest_sessionfinish(self, session, exitstatus):
        self.append('session_finish', exitstatus=int(exitstatus))
