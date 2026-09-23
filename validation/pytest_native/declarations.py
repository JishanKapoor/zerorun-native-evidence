"""Finite original pytest 8.4.2 phase/report/terminal handoff declarations.

The run and attempt are explicit acquisition identities, not inferred retries.
Only stock plugins and the authored fixture configuration are qualified here.
"""

RUNNER = '_pytest/runner.py'
TERMINAL = '_pytest/terminal.py'
REPORTS = '_pytest/reports.py'
GRAMMAR = '1.4.0'
IDENTITY = dict(run='str', candidate='str', phase='str', attempt='int', obligation='str')
REPORT_ASSIGN = 'report: TestReport = ihook.pytest_runtest_makereport(item=item, call=call)'
HOOK_CALL = 'ihook.pytest_runtest_logreport(report=report)'
CATEGORY_ASSIGN = 'category, letter, word = res.category, res.letter, res.word'
STATS_CALL = 'self._add_stats(category, [rep])'
ABSENT = '__zerorun_missing_native_report__'


def stored(record, name):
    return {'record': record, 'stored': name}


def report_field(local, name):
    return {'local': local, 'path': [stored('report', name)]}


def destination_field(name):
    return {'local': 'self', 'path': [stored('terminal', 'stats'),
            {'index_local': 'category'}, {'index': -1}, stored('report', name)],
            'default': ABSENT}


def profile():
    p = dict(api='zerorun.extensions/1', id='pytest-native-phase-report-path', version='1.0.0',
             identity=IDENTITY.copy(), facts={}, sites={}, rules=[],
             record_types={
                 'report': dict(module='_pytest.reports', name='TestReport', path=REPORTS,
                                fields=['nodeid', 'when', 'outcome']),
                 'terminal': dict(module='_pytest.terminal', name='TerminalReporter', path=TERMINAL,
                                  fields=['stats'])},
             justification='Original pytest per-phase report handoff and actual terminal statistics destination; authored stock-plugin configuration')

    for name, kind, path, function, anchor, position, local in [
        ('report-produced', 'report-produced', RUNNER, 'call_and_report', REPORT_ASSIGN, 'after', 'report'),
        ('report-hook-input', 'report-hook-input', RUNNER, 'call_and_report', HOOK_CALL, 'before', 'report'),
        ('terminal-decision', 'terminal-decision', TERMINAL, 'TerminalReporter.pytest_runtest_logreport', CATEGORY_ASSIGN, 'after', 'rep'),
        ('terminal-stats-input', 'terminal-stats-input', TERMINAL, 'TerminalReporter.pytest_runtest_logreport', STATS_CALL, 'before', 'rep'),
        ('terminal-stats-commit', 'terminal-stats-commit', TERMINAL, 'TerminalReporter.pytest_runtest_logreport', STATS_CALL, 'after', 'rep'),
    ]:
        identity = dict(run={'context': 'run'}, candidate={'context': 'candidate'},
                        attempt={'context': 'attempt'}, obligation=report_field(local, 'nodeid'),
                        phase={'local': 'when'} if path == RUNNER else report_field(local, 'when'))
        fields = dict(nodeid=report_field(local, 'nodeid'), phase_value=report_field(local, 'when'),
                      outcome=report_field(local, 'outcome'))
        if name == 'report-produced':
            # Preserve native input phase independently of the returned report.
            fields['phase_value'] = {'local': 'when'}
        if name in ('terminal-decision', 'terminal-stats-input'):
            fields.update({field: {'local': field} for field in ('category', 'letter', 'word')})
        if name == 'terminal-stats-commit':
            fields = dict(nodeid=destination_field('nodeid'), phase_value=destination_field('when'),
                          outcome=destination_field('outcome'))
        p['facts'][kind] = {field: 'str' for field in fields}
        p['sites'][name] = dict(kind=kind, path=path, function=function, anchor=anchor,
            position=position, multiplicity=1, projection={**identity, **fields},
            justification='Actual original native report/categorization/storage at ' + name)

    for source, target, fields in [
        ('report-produced', 'report-hook-input', ['nodeid', 'phase_value', 'outcome']),
        ('report-hook-input', 'terminal-decision', ['nodeid', 'phase_value', 'outcome']),
        ('terminal-decision', 'terminal-stats-input', ['nodeid', 'phase_value', 'outcome', 'category', 'letter', 'word']),
        ('terminal-stats-input', 'terminal-stats-commit', ['nodeid', 'phase_value', 'outcome']),
    ]:
        for field in [None, *fields]:
            p['rules'].append(dict(id=source + '-to-' + target + '-' + ('required' if field is None else field),
                check='C1' if field is None else 'C2', producer=source, consumer=target,
                keys=list(IDENTITY), when=None, source_field=field, target_field=field,
                operator='exists' if field is None else 'identity', statuses=[], target_mapping=None,
                requires=[source, target], justification='Native report identity/phase/outcome or terminal decision remains unchanged across the declared handoff'))
    return p


def case_inventory(expected, run, attempt, *, candidate='authored-pytest', filename='test_native_controls.py'):
    """Exact prospective fixture population; no production report is an oracle."""
    return [dict(run=run, candidate=candidate, attempt=attempt, phase=phase,
                 obligation=filename + '::' + name)
            for name, outcomes in expected.items() for phase, _ in outcomes]


def expected_site_identities(expected, run, attempt, *, candidate='authored-pytest', filename='test_native_controls.py'):
    inventory = case_inventory(expected, run, attempt, candidate=candidate, filename=filename)
    return {site: [dict(row) for row in inventory] for site in profile()['sites']}
