"""All campaign summaries must exclude vacuous evidence-bearing products."""
import ast
import importlib
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'validation'))


@pytest.mark.parametrize('family',['swe_reporting','swe_joined','inspect_path','swe_pytest'])
def test_actual_recipe_denominator_excludes_inapplicable_but_keeps_real_failure(family):
    # Import the actual helper module; its function is the one called by the
    # executable campaign, not a separately authored implementation.
    module=importlib.import_module(family+('.bridge' if family=='swe_pytest' else '.campaign'))
    witnessed=dict(evidence_ids=['producer','consumer'],reasons=['values_equal'],status='CONFORMS')
    missing=dict(evidence_ids=['consumer'],reasons=['required_producer_missing'],status='VIOLATION')
    ambiguous=dict(evidence_ids=['producer1','producer2','consumer'],reasons=['ambiguous_or_duplicate_native_identity'],status='INCONCLUSIVE')
    vacuous=dict(evidence_ids=['producer'],reasons=['no_applicable_disposition'],status='CONFORMS')
    guarded=dict(evidence_ids=['native-empty-operand'],reasons=['native_rule_guard_not_applicable'],status='CONFORMS')
    empty=dict(evidence_ids=[],reasons=['no_applicable_disposition'],status='CONFORMS')
    assert module.applicable_records([witnessed,missing,ambiguous,vacuous,guarded,empty])==[witnessed,missing,ambiguous]
    path=ROOT/'validation'/family/'campaign.py'
    tree=ast.parse(path.read_text())
    assignments=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='relevant' for t in n.targets)]
    assert len(assignments)==1 and isinstance(assignments[0].value,ast.Call)
    assert assignments[0].value.func.id=='select_records'


@pytest.mark.parametrize('family',['swe_reporting','swe_joined','inspect_path','swe_pytest'])
def test_reference_domain_does_not_shrink_when_all_observations_are_lost(family):
    import copy
    from zerorun_harness.api import digest
    from zerorun_harness.declarative import evaluate
    domain=importlib.import_module(family+'.domain')
    ident=dict(run='r',candidate='c',phase='call',attempt=1,obligation='test')
    profile=importlib.import_module('pytest_native.declarations').profile()
    for rule in profile['rules']:rule['when']={'field':'outcome','in':['passed']}
    facts={site:[dict(identity=ident.copy(),values=dict(nodeid='test',phase_value='call',outcome='passed',
        **({'category':'passed','word':'PASSED','letter':'.'} if site in ['terminal-decision','terminal-stats-input'] else {})))] for site in profile['sites']}
    declared=domain.reference_domain(profile,facts)
    assert len(declared['rows'])==19
    material=dict(id='missing',version='1',inventory=[ident],source_sha256='1'*64,input_sha256='2'*64)
    # Real loss invalidates current observation coverage. The independent
    # population never supplies a grade or changes a checker status.
    health=dict(binding_sha256='3'*64,sites={s:False for s in profile['sites']},transport={'1':True},
                native_complete={r['id']:True for r in profile['rules']},qualification_sha256='4'*64)
    result=evaluate(profile,material,[],health,'3'*64)
    selected=domain.select_records(result['records'],declared)
    assert len(selected)==19 and all(r['status']=='INCONCLUSIVE' for r in selected)
    assert all(r['reasons']==['unqualified_semantic_sites'] for r in selected)
    trusted=copy.deepcopy(health);trusted['sites']={s:True for s in profile['sites']}
    assumed=evaluate(profile,material,[],trusted,'3'*64)
    assert all(r['status']=='CONFORMS' and r['reasons']==['no_applicable_disposition'] for r in assumed['records'])
    assert domain.reference_domain(profile,facts)==declared
    # Erasing an entire result row must fail, not decrease the denominator.
    with pytest.raises(ValueError):domain.select_records(result['records'][:-1],declared)


def test_native_when_predicate_domain_uses_original_value_not_observed_status():
    from swe_reporting.domain import reference_domain,select_records
    p=dict(sites={'producer':{'kind':'p','projection':{'id':{'context':'id'},'status':{'local':'status'}}},'consumer':{'kind':'c','projection':{'id':{'context':'id'}}}},facts={'p':{},'c':{}},
        rules=[dict(id='rule',producer='p',consumer='c',keys=['id'],when={'field':'status','in':['accept']})])
    facts={'producer':[dict(identity={'id':'wanted'},values={'status':'accept'}),dict(identity={'id':'skipped'},values={'status':'skip'})],
           'consumer':[dict(identity={'id':'wanted'},values={}),dict(identity={'id':'skipped'},values={})]}
    domain=reference_domain(p,facts)
    wanted=dict(relationship='rule',identity={'id':'wanted'},status='INCONCLUSIVE',reasons=['missing_native_producer'],evidence_ids=[])
    skipped=dict(relationship='rule',identity={'id':'skipped'},status='CONFORMS',reasons=['no_applicable_disposition'],evidence_ids=['consumer'])
    assert select_records([wanted,skipped],domain)==[wanted]
    interrupted=reference_domain(p,facts,{'rule':False},[{'id':'wanted'},{'id':'skipped'}])
    assert select_records([wanted,skipped],interrupted)==[wanted,skipped]


def test_interruption_keeps_possible_domains_even_when_both_native_operands_absent():
    from swe_reporting.domain import reference_domain,select_records
    p=dict(sites={'producer':{'kind':'p','projection':{'phase':{'literal':'writer'},'id':{'context':'id'},'role':{'literal':'write'}}},
                  'consumer':{'kind':'c','projection':{'phase':{'literal':'writer'},'id':{'context':'id'}}}},facts={'p':{},'c':{}},
        rules=[dict(id='rule',producer='p',consumer='c',keys=['id','phase'],when={'field':'role','in':['write']})])
    facts={'producer':[],'consumer':[]};inventory=[dict(id='a',phase='writer'),dict(id='a',phase='unrelated')]
    domain=reference_domain(p,facts,{'rule':False},inventory)
    assert len(domain['rows'])==1 and domain['rows'][0]['identity']==dict(id='a',phase='writer')
    row=dict(relationship='rule',identity=dict(id='a',phase='writer'),evidence_ids=[],status='INCONCLUSIVE',reasons=['missing_native_producer'])
    assert select_records([row],domain)==[row]
    p['sites']['consumer']['projection']['phase']={'literal':'unrelated'}
    assert len(reference_domain(p,facts,{'rule':False},inventory)['rows'])==2
