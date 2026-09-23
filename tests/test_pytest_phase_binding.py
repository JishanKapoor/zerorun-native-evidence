"""Pure qualification of the authored pytest profile; no nested pytest runs.

These tests use actual native source and native record classes but do not call
pytest.main, run a test fixture, or execute a transformed native pytest method.
Actual native executions are separately frozen and charged by the campaign.
"""
import ast
import copy
import importlib.metadata
import importlib.util
from pathlib import Path

import _pytest
from _pytest.reports import TestReport as NativeReport
from _pytest.terminal import TerminalReporter as NativeTerminal
import pytest

from zerorun_harness.api import InvalidEvidence, digest
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.declarative import evaluate
from zerorun_harness.records import register_records


HELPERS = Path(__file__).resolve().parents[1] / 'validation' / 'pytest_native'


def helper(name):
    spec = importlib.util.spec_from_file_location('phase_binding_' + name, HELPERS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


decl = helper('declarations')
fixture = helper('fixtures')


@pytest.fixture(scope='module')
def bound():
    assert importlib.metadata.version('pytest') == '8.4.2'
    root = Path(_pytest.__file__).resolve().parent.parent
    sources = {path: (root / path).read_text(encoding='utf-8')
               for path in (decl.RUNNER, decl.TERMINAL, decl.REPORTS)}
    profile = decl.profile()
    binding = generate_binding(profile, sources, grammar_version=decl.GRAMMAR)
    registry = register_records(profile, binding, {'report': NativeReport, 'terminal': NativeTerminal})
    return profile, binding, registry


class Sink:
    def __init__(self):
        self.events = []
        self.rejected = 0

    def emit(self, event):
        if type(event) is not dict:
            self.rejected += 1
            return False
        self.events.append(copy.deepcopy(event))
        return True


def callback(bound, *, run='pure-run', attempt=1):
    profile, binding, registry = bound
    sink = Sink()
    observe = recorder(profile, binding, sink, 123, records=registry,
                       context=dict(run=run, candidate='authored-pytest', attempt=attempt))
    return observe, sink


def native_report(*, name='test_pass', phase='call', outcome='passed'):
    return NativeReport(nodeid='test_native_controls.py::' + name,
                        location=('test_native_controls.py', 1, name),
                        keywords={}, outcome=outcome, longrepr=None, when=phase)


def local_state(report, *, when=None, stats=None, category='passed', word='PASSED', letter='.'):
    terminal = object.__new__(NativeTerminal)
    terminal.__dict__['stats'] = {category: [report]} if stats is None else stats
    return dict(report=report, rep=report, when=report.when if when is None else when,
                self=terminal, category=category, word=word, letter=letter)


def assess(bound, events):
    """Synthetic health is only a unit-test premise, not native qualification."""
    profile, binding, _ = bound
    inventory = []
    for event in events:
        if event['identity'] not in inventory:
            inventory.append(copy.deepcopy(event['identity']))
    case = dict(id='pure-profile-control', version='1', inventory=inventory,
                source_sha256=digest(binding['original_sources']), input_sha256=digest(inventory))
    health = dict(binding_sha256=binding['sha256'], sites={site: True for site in profile['sites']},
                  transport={'123': True}, native_complete={r['id']: True for r in profile['rules']},
                  qualification_sha256='1' * 64)
    return evaluate(profile, case, events, health, binding['sha256'])


def test_five_original_sites_and_nineteen_finite_relations(bound):
    profile, binding, _ = bound
    assert len(profile['sites']) == len(binding['sites']) == 5
    assert len(profile['rules']) == 19
    assert {r['operator'] for r in profile['rules']} == {'identity', 'exists'}
    assert all(r['keys'] == list(decl.IDENTITY) for r in profile['rules'])


def test_transform_only_adds_five_nonmangled_observation_calls(bound):
    class RemoveHooks(ast.NodeTransformer):
        count = 0

        def visit_Expr(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == '__zr_observe__':
                self.count += 1
                return None
            return self.generic_visit(node)

    _, binding, _ = bound
    remover = RemoveHooks()
    for path, transformed in binding['transformed'].items():
        clean = remover.visit(ast.parse(transformed))
        assert ast.dump(clean) == ast.dump(ast.parse(binding['original'][path]))
    assert remover.count == 5


@pytest.mark.parametrize('grammar', ['1.2.0', '1.3.0'])
def test_previous_grammars_do_not_silently_admit_new_native_profile(bound, grammar):
    profile, binding, _ = bound
    with pytest.raises(InvalidEvidence):
        generate_binding(profile, binding['original'], grammar_version=grammar)


@pytest.mark.parametrize('phase,outcome', [('setup', 'passed'), ('setup', 'failed'),
    ('call', 'passed'), ('call', 'failed'), ('call', 'skipped'), ('teardown', 'failed')])
def test_actual_report_fields_preserved_across_all_five_projected_sites(bound, phase, outcome):
    observe, sink = callback(bound)
    report = native_report(phase=phase, outcome=outcome)
    state = local_state(report)
    for site in decl.profile()['sites']:
        assert observe(site, state)
    assert sink.rejected == 0
    assert len(sink.events) == 5
    assert {e['identity']['phase'] for e in sink.events} == {phase}
    assert {e['values']['outcome'] for e in sink.events} == {outcome}
    assert assess(bound, sink.events)['counts'] == {'CONFORMS': 19}


def test_native_runner_input_phase_is_not_replaced_with_report_phase(bound):
    observe, sink = callback(bound)
    state = local_state(native_report(phase='teardown'), when='setup')
    observe('report-produced', state)
    observe('report-hook-input', state)
    produced, handed = sink.events
    assert produced['identity']['phase'] == handed['identity']['phase'] == 'setup'
    assert produced['values']['phase_value'] == 'setup'
    assert handed['values']['phase_value'] == 'teardown'
    result = assess(bound, sink.events)
    record = next(r for r in result['records']
                  if r['relationship'] == 'report-produced-to-report-hook-input-phase_value')
    assert record['status'] == 'VIOLATION'


@pytest.mark.parametrize('field,value', [('nodeid', 'other.py::test_other'), ('when', 'setup'), ('outcome', 'failed')])
def test_commit_reads_actual_destination_not_incoming_report(bound, field, value):
    observe, sink = callback(bound)
    report, stored = native_report(), native_report()
    stored.__dict__[field] = value
    state = local_state(report, stats={'passed': [stored]})
    observe('terminal-stats-input', state)
    observe('terminal-stats-commit', state)
    assert sink.events[0]['identity'] == sink.events[1]['identity']
    expected_field = 'phase_value' if field == 'when' else field
    assert sink.events[1]['values'][expected_field] == value
    result = assess(bound, sink.events)
    record = next(r for r in result['records']
                  if r['relationship'] == 'terminal-stats-input-to-terminal-stats-commit-' + expected_field)
    assert record['status'] == 'VIOLATION'


@pytest.mark.parametrize('stats', [{}, {'passed': []}, {'failed': []}])
def test_missing_destination_is_explicit_sentinel_not_a_fabricated_commit(bound, stats):
    observe, sink = callback(bound)
    state = local_state(native_report(), stats=stats)
    observe('terminal-stats-input', state)
    observe('terminal-stats-commit', state)
    assert sink.rejected == 0
    assert set(sink.events[-1]['values'].values()) == {decl.ABSENT}
    result = assess(bound, sink.events)
    checks = [r for r in result['records'] if r['relationship'].startswith('terminal-stats-input-to-terminal-stats-commit-')]
    assert sum(r['status'] == 'VIOLATION' for r in checks) == 3


def test_wrong_prior_report_in_same_category_is_not_a_successful_store(bound):
    observe, sink = callback(bound)
    current, prior = native_report(name='test_fail'), native_report(name='test_pass')
    state = local_state(current, stats={'passed': [prior]})
    observe('terminal-stats-input', state)
    observe('terminal-stats-commit', state)
    assert sink.events[-1]['values']['nodeid'] == prior.nodeid
    record = next(r for r in assess(bound, sink.events)['records']
                  if r['relationship'] == 'terminal-stats-input-to-terminal-stats-commit-nodeid')
    assert record['status'] == 'VIOLATION'


def test_custom_report_and_storage_classes_are_not_projected(bound):
    observe, sink = callback(bound)
    class AlteredReport(NativeReport):
        pass
    report = object.__new__(AlteredReport)
    report.__dict__.update(nodeid='test_native_controls.py::test_pass', when='call', outcome='passed')
    assert not observe('report-produced', local_state(report))
    class AlteredList(list):
        def __getitem__(self, index):
            raise AssertionError('Custom storage callback must not run')
    assert not observe('terminal-stats-commit', local_state(native_report(), stats={'passed': AlteredList()}))
    assert sink.events == [] and sink.rejected == 2


def test_prospective_fixture_inventory_preserves_phase_attempt_and_parameter_identity():
    first = decl.case_inventory(fixture.EXPECTED, 'first', 1)
    second = decl.case_inventory(fixture.EXPECTED, 'second', 2)
    assert len(first) == len(second) == 28
    assert len({tuple(sorted(row.items())) for row in first + second}) == 56
    errors = [row for row in first if row['obligation'].endswith('::test_two_phase_errors')]
    assert {row['phase'] for row in errors} == {'setup', 'teardown'}
    assert len({row['obligation'] for row in first if 'test_parameter[' in row['obligation']}) == 2
    sites = decl.expected_site_identities(fixture.EXPECTED, 'first', 1)
    assert len(sites) == 5 and all(rows == first for rows in sites.values())


def test_run_attempt_are_explicit_context_and_not_report_attributes(bound):
    observe, sink = callback(bound, run='second-process', attempt=2)
    report = native_report()
    report.__dict__.update(run='untrusted-report-run', attempt=99)
    observe('report-produced', local_state(report))
    assert sink.events[0]['identity']['run'] == 'second-process'
    assert sink.events[0]['identity']['attempt'] == 2
