"""The native campaign census retains unknowns and rejects vacuous products."""
import importlib.util
from pathlib import Path
import copy

import pytest


PATH = Path(__file__).resolve().parents[1]/'validation/evalplus_path/expectations.py'
spec = importlib.util.spec_from_file_location('evalplus_census_expectations', PATH)
expectations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expectations)


def test_consumer_only_missing_producer_is_retained_in_comprehensive_census():
    unknown = dict(relationship='relation',identity={},evidence_ids=['actual-parent-element'], reasons=['missing_native_producer'], status='INCONCLUSIVE')
    assert expectations.applicable({}, {'records':[unknown]}, [], []) == [unknown]


def test_vacuous_native_guard_and_disposition_are_excluded_even_with_evidence():
    rows = [dict(evidence_ids=['native-parent'], reasons=[reason], status='CONFORMS')
            for reason in ('no_applicable_disposition', 'native_rule_guard_not_applicable')]
    assert expectations.applicable_records(rows) == []


def test_genuine_success_fault_and_ambiguity_keep_exact_rows_without_regrading():
    rows = [dict(evidence_ids=['actual-native'], reasons=[reason], status=status)
            for reason,status in [('values_equal','CONFORMS'), ('required_consumer_missing','VIOLATION'),
                                  ('ambiguous_or_duplicate_native_identity','INCONCLUSIVE')]]
    assert expectations.applicable_records(rows) == rows
    assert all(a is b for a,b in zip(expectations.applicable_records(rows), rows))


def test_unwitnessed_product_needs_independent_domain_evidence_before_exclusion():
    row = dict(evidence_ids=[], reasons=['missing_native_producer'], status='INCONCLUSIVE')
    assert expectations.applicable_records([row]) == []
    row.update(relationship='relation',identity={})
    assert expectations.applicable({}, {'records':[row]}, [], []) == [row]


def fixture(role='worker'):
    p=dict(rules=[dict(id='relation',producer='p',consumer='c',keys=['obligation'],when=None)],sites={
        'source':dict(kind='p',producer_role=role,projection={'obligation':{'local':'i'}}),
        'target':dict(kind='c',producer_role='parent',projection={'obligation':{'local':'i'}})})
    row=dict(relationship='relation',identity={'obligation':0},evidence_ids=[],reasons=['missing_native_producer'],status='INCONCLUSIVE')
    ref=dict(journal={'parent':[],'worker':[]},parent_journal_lost=False,returned={'grade':'pass'},exception=None,native_bank_calls=1)
    return p,row,ref


def scope(p,row,ref):
    return expectations.reporting_census(p,{'records':[row]},ref)[0]


def test_completely_lost_observation_is_retained_when_independent_producer_exists():
    p,row,ref=fixture()
    ref['journal']['worker']=[dict(name='source',identity={'obligation':0},values={})]
    result=scope(p,row,ref)
    assert result['include'] and result['reason']=='independent_native_witness'


def test_completely_lost_observation_is_retained_when_independent_consumer_exists():
    p,row,ref=fixture()
    ref['journal']['parent']=[dict(name='target',identity={'obligation':0},values={})]
    assert scope(p,row,ref)['include']


@pytest.mark.parametrize('reason',['no_applicable_disposition','native_rule_guard_not_applicable'])
def test_observer_vacuity_cannot_hide_independently_witnessed_native_obligation(reason):
    p,row,ref=fixture()
    row.update(status='CONFORMS',reasons=[reason])
    ref['journal']['worker']=[dict(name='source',identity={'obligation':0},values={})]
    assert scope(p,row,ref)['include']


def test_only_actual_native_status_can_prove_false_disposition():
    p,row,ref=fixture()
    p['rules'][0]['when']={'field':'accepted','in':[True]}
    ref['journal']['worker']=[dict(name='source',identity={'obligation':0},values={'accepted':False})]
    assert not scope(p,row,ref)['include']
    ref['journal']['worker'][0]['values']['accepted']=True
    assert scope(p,row,ref)['include']


def test_missing_independent_guard_stays_in_domain_but_actual_false_guard_does_not():
    p,row,ref=fixture()
    p['rules'][0]['guard']={'kind':'guard','field':'raw','in':[0]}
    p['sites']['guard']=dict(kind='guard',producer_role='parent',projection={'obligation':{'literal':0}})
    assert scope(p,row,ref)['include']
    ref['journal']['parent']=[dict(name='guard',identity={'obligation':0},values={'raw':1})]
    assert not scope(p,row,ref)['include']


@pytest.mark.parametrize('returns',[[],[dict(name='native-worker-return',values={'journal_lost':True})],
    [dict(name='native-worker-return',values={'journal_lost':False})]*2])
def test_unclosed_lost_or_ambiguous_worker_trace_cannot_exclude_unknown(returns):
    profile,row,ref=fixture()
    ref['journal']['worker']=copy.deepcopy(returns)
    assert scope(profile,row,ref)['include']


def test_completed_independent_worker_can_prove_no_actual_selected_producer():
    p,row,ref=fixture()
    ref['journal']['worker']=[dict(name='native-worker-return',values={'journal_lost':False})]
    result=scope(p,row,ref)
    assert not result['include'] and result['reason']=='completed_independent_worker_has_no_applicable_producer'


def test_literal_source_identity_proves_structurally_impossible_product():
    p,row,ref=fixture()
    p['sites']['source']['projection']['obligation']={'literal':1}
    result=scope(p,row,ref)
    assert not result['include'] and result['reason']=='outside_source_literal_identity_domain'


def test_parent_journal_loss_cannot_exclude_missing_parent_product():
    p,row,ref=fixture('parent')
    ref['parent_journal_lost']=True
    assert scope(p,row,ref)['include']


def test_completed_independent_parent_can_prove_absent_native_elements():
    p,row,ref=fixture('parent')
    assert not scope(p,row,ref)['include']


def test_zero_bank_preflight_requires_exact_independent_native_exception_marker():
    p,row,ref=fixture()
    ref.update(native_bank_calls=0,returned=None,exception='TypeError')
    assert scope(p,row,ref)['include']
    ref['journal']['parent']=[dict(name='native-parent-exception',values={'exception':'TypeError'})]
    result=scope(p,row,ref)
    assert not result['include'] and result['reason']=='independent_zero_bank_preflight_control'
