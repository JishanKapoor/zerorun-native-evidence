"""Actual provenance attribution must preserve missing and ambiguous phase IDs."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'validation'))
from swe_pytest.bridge import phase_attribution,verify_audit_outcomes,duplicate_evidence,applicable_records
from swe_pytest.reference import py_facts,selected,points


def terminal(phase,word='ERROR',node='file.py::test'):
    return dict(identity=dict(phase=phase),values=dict(nodeid=node,word=word))


def test_same_native_node_same_status_two_actual_phases_stays_ambiguous():
    rows=phase_attribution([terminal('setup'),terminal('teardown')],{'file.py::test':'ERROR'})
    assert rows[0]['disposition']=='INCONCLUSIVE_PHASE_AMBIGUITY'
    assert rows[0]['actual_terminal_occurrences']==2


def test_unique_failure_and_missing_legacy_count_are_distinct():
    rows=phase_attribution([terminal('call','FAILED')],{'file.py::test':'FAILED','[1]':'SKIPPED'})
    indexed={r['nodeid']:r for r in rows}
    assert indexed['file.py::test']['disposition']=='UNIQUE_NATIVE_PHASE'
    assert indexed['[1]']['disposition']=='NO_NATIVE_NODE_ATTRIBUTION'


def test_duplicate_native_occurrences_are_retained_not_invented_as_retries():
    rows=phase_attribution([terminal('call','FAILED'),terminal('call','FAILED')],{'file.py::test':'FAILED'})
    assert rows[0]['actual_terminal_occurrences']==2
    assert rows[0]['actual_native_phases']==['call']
    assert 'attempt' not in rows[0]


def test_independent_terminal_commit_reference_reads_actual_destination():
    row=dict(locals=dict(rep=dict(nodeid='x',when='call',outcome='passed'),
                         stored_report=dict(nodeid='wrong',when='setup',outcome='failed')))
    fact=py_facts('terminal-stats-commit',row,'run',2)
    assert fact['identity']['obligation']=='x' and fact['identity']['phase']=='call'
    assert fact['values']==dict(nodeid='wrong',phase_value='setup',outcome='failed')


def test_independent_method_point_selector_finds_actual_native_statement():
    source='class Reporter:\n def report(self, rep):\n  self.values.append(rep)\n  return rep\n'
    point=points(source,'Reporter.report','self.values.append(rep)')
    assert point[:2]==(3,3)


def test_only_exact_declared_parser_ambiguity_is_accepted():
    import copy
    import pytest
    expected=[dict(relationship='parser-required-store',obligation='test')]
    row=dict(relationship='parser-required-store',identity=dict(obligation='test'),status='INCONCLUSIVE',
             reasons=['ambiguous_or_duplicate_native_identity'])
    verify_audit_outcomes([row],expected)
    for key,value in [('status','VIOLATION'),('reasons',['transport_loss']),('relationship','other')]:
        changed=copy.deepcopy(row);changed[key]=value
        with pytest.raises(ValueError):verify_audit_outcomes([changed],expected)
    with pytest.raises(ValueError):verify_audit_outcomes([row],[])
    with pytest.raises(ValueError):verify_audit_outcomes([],expected)
    with pytest.raises(ValueError):verify_audit_outcomes([row,row],expected)


def test_vacuous_producer_only_evidence_is_excluded_from_applicable_denominator():
    vacuous=dict(evidence_ids=['actual-producer'],reasons=['no_applicable_disposition'])
    guarded=dict(evidence_ids=['actual-empty-operand'],reasons=['native_rule_guard_not_applicable'])
    witnessed=dict(evidence_ids=['actual-producer','actual-consumer'],reasons=['values_equal'])
    empty=dict(evidence_ids=[],reasons=['no_applicable_disposition'])
    assert applicable_records([vacuous,guarded,witnessed,empty])==[witnessed]


def test_actual_phase_missing_or_parser_corruption_cannot_justify_ambiguity():
    import copy
    import pytest
    reports=[];facts=[]
    for name,phases,statuses in [('test_teardown_error',[('setup','passed'),('call','passed'),('teardown','failed')],['PASSED','ERROR']),
                               ('test_two_phase_errors',[('setup','failed'),('teardown','failed')],['ERROR','ERROR'])]:
        node='test_native_controls.py::'+name
        reports.extend(dict(event='test_report',nodeid=node,when=phase,outcome=outcome) for phase,outcome in phases)
        facts.extend(dict(identity=dict(obligation=node),values=dict(raw=status)) for status in statuses)
    assert len(duplicate_evidence(reports,facts))==2
    with pytest.raises(ValueError):duplicate_evidence(reports[:-1],facts)
    altered=copy.deepcopy(reports);altered[-1]['when']='call'
    with pytest.raises(ValueError):duplicate_evidence(altered,facts)
    altered=copy.deepcopy(facts);altered[-1]['values']['raw']='PASSED'
    with pytest.raises(ValueError):duplicate_evidence(reports,altered)

def test_registry_freezes_after_stock_native_configuration(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    script=r'''
import io
from pathlib import Path
import _pytest
from _pytest.config import Config
from _pytest.reports import TestReport
from _pytest.terminal import TerminalReporter
from pytest_native.declarations import profile,GRAMMAR,RUNNER,REPORTS,TERMINAL
from zerorun_harness.binding import generate_binding
from zerorun_harness.records import register_records
from zerorun_harness.projection import project
from zerorun_harness._telemetry_protocol import PrimitiveError
p=profile();root=Path(_pytest.__file__).parent.parent
b=generate_binding(p,{name:(root/name).read_text(encoding='utf-8') for name in [RUNNER,REPORTS,TERMINAL]},grammar_version=GRAMMAR)
classes={'report':TestReport,'terminal':TerminalReporter}
early=register_records(p,b,classes)
config=Config.fromdictargs({},[])
try:
 terminal=TerminalReporter(config,io.StringIO())
 report=TestReport(nodeid='a',location=('a',1,'a'),keywords={},outcome='passed',longrepr=None,when='setup')
 terminal.stats['']=[report]
 state=dict(self=terminal,rep=report,category='')
 field=p['sites']['terminal-stats-commit']['projection']['nodeid']
 try:project(field,state,records=early)
 except PrimitiveError as error:assert str(error)=='Native record class changed after registration'
 else:raise AssertionError('Earlier registry accepted stock native class mutation')
 late=register_records(p,b,classes)
 assert project(field,state,records=late)=='a'
 TerminalReporter.authored_later_mutation=True
 try:project(field,state,records=late)
 except PrimitiveError:pass
 else:raise AssertionError('Later mutation was accepted')
 del TerminalReporter.authored_later_mutation
finally:config._ensure_unconfigure()
print('native_configuration_order_verified; pytest.main calls=0')
'''
    env=os.environ.copy();env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    env['PYTHONPATH']=os.pathsep.join([str(root/'src'),str(root/'validation')])
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'pytest.main calls=0' in result.stdout
