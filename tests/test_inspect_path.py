"""Prospective Inspect profile and evidence-logic controls, no native evals."""
import copy
from pathlib import Path
import sys

import pytest

from zerorun_harness.api import digest, InvalidEvidence
from zerorun_harness.binding import generate_binding
from zerorun_harness.declarative import evaluate

VALIDATION=Path(__file__).resolve().parents[1]/'validation'
sys.path.insert(0,str(VALIDATION))
from inspect_path import declarations as decl


def sources():
    root=VALIDATION/'inspect_path/sources'
    return {decl.RUN:(root/'run.py.txt').read_bytes().decode(),decl.RESULTS:(root/'results.py.txt').read_bytes().decode(),
            decl.METRIC:(root/'metric.py.txt').read_bytes().decode()}


def test_original_async_assignment_and_real_consumer_calls_admit_only_opt_in():
    p=decl.profile()
    b=generate_binding(p,sources(),grammar_version='1.3.0')
    assert len(p['sites'])==len(b['sites'])==16
    assert {r['line'] for r in b['sites'] if r['site'] in ['score-decision','score-commit']}=={3027}
    assert 'results[scorer_name] = SampleScore' in p['sites']['score-commit']['anchor']
    with pytest.raises(InvalidEvidence):generate_binding(p,sources())


def test_scientific_handoff_does_not_require_consumer_ordinal_or_activation():
    p=decl.profile()
    consumer=p['sites']['raw-consumer']
    assert consumer['batch']['ordinal']=='acquisition'
    assert consumer['projection']['activation']=={'literal':0}
    assert consumer['projection']['slot']=={'literal':0}
    for field in ['sample','epoch']:
        assert consumer['projection'][field]['item'] is True
        assert 'stored' in consumer['projection'][field]['path'][0]
    for site in ['reduced-input','reduced-returned']:
        assert p['sites'][site]['projection']['epoch']=={'literal':0}
        assert p['sites'][site]['projection']['activation']=={'activation':True}
        assert p['sites'][site]['projection']['view']=={'literal':'reduced'}


def classification(values,count,*,lose_end=False):
    p=decl.profile();p['rules']=[r for r in p['rules'] if r['check']=='C3']
    b=generate_binding(p,sources(),grammar_version='1.3.0')
    identity=dict(run='unit',candidate='logic-control',phase='native-unscored-count',attempt=1,obligation='score',
                  activation=1,scorer='scorer_a',sample=0,epoch=0,view='"mean"',slot=0)
    source=digest(b['original_sources'])
    def event(seq,kind,site,values,slot=0):
        return dict(id='42:'+str(seq),kind=kind,site=site,identity={**identity,'slot':slot},values=values,
                    producer=42,seq=seq,source_sha256=source,binding_sha256=b['sha256'])
    events=[event(i+1,'classification-input','classification-input',dict(raw=v,role='classification-input'),i)
            for i,v in enumerate(values)]
    group={k:v for k,v in identity.items() if k!='slot'}
    begin=dict(schema='zerorun-native-batch/1',site='classification-input',producer=42,binding_sha256=b['sha256'],
               batch=1,size=len(values),stage='begin',identity=group)
    if lose_end:
        events=events[:-1]
    journal=[begin,*copy.deepcopy(events)]
    if not lose_end:journal.append({**begin,'stage':'end'})
    target=event(len(values)+1,'classification-count','classification-count',dict(count=count,input_size=len(values),role='classification-count'))
    events.append(target);journal.append(copy.deepcopy(target))
    material=dict(id='unit',version='1',inventory=[{**identity,'slot':i} for i in range(max(1,len(values)))],source_sha256=source,input_sha256='b'*64)
    health=dict(binding_sha256=b['sha256'],sites={s:True for s in p['sites']},transport={'42':True},
                native_complete={'native-unscored-classification':True},qualification_sha256='a'*64,batch_journal=journal)
    return evaluate(p,material,events,health,b['sha256'])['records'][0]


@pytest.mark.parametrize('values,count', [([],0),(['0.0'],0),(['1.0','0.5'],0),(['NaN'],1),(['NaN','1.0','NaN'],2)])
def test_finite_native_unscored_count_policy_and_empty_batch(values,count):
    result=classification(values,count)
    assert result['status']=='CONFORMS'
    if not values:
        assert result['reasons']==['native_rule_guard_not_applicable']


@pytest.mark.parametrize('values,count', [(['0.0'],1),(['NaN'],0),(['NaN','1.0'],0)])
def test_contradictory_native_unscored_count_detected(values,count):
    assert classification(values,count)['status']=='VIOLATION'


def test_lost_batch_tail_cannot_prove_no_unscored_inputs():
    assert classification(['1.0','0.0'],0,lose_end=True)['status']=='INCONCLUSIVE'


def test_reference_does_not_import_framework_or_production_policy():
    import ast
    tree=ast.parse((VALIDATION/'inspect_path/reference.py').read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(n and ('zerorun' in n or 'declarations' in n) for n in imports)


def test_reference_multiline_entry_and_completed_commit_are_each_single():
    from inspect_path.reference import point_rows
    rows=[dict(call=1,path='x',function='f',event='line',line=line,locals={'value':i})
          for i,line in enumerate([9,10,11,12,10,13,9,10,11,12,10,13])]
    before=list(point_rows(rows,'x','f',{10:12},'before'))
    after=list(point_rows(rows,'x','f',{10:12},'after'))
    assert [r['locals']['value'] for r in before]==[1,7]
    assert [r['locals']['value'] for r in after]==[5,11]


def test_reference_preserves_nan_token_and_reduced_epoch_scope():
    from inspect_path.reference import facts
    item=dict(sample_id=3,score=dict(raw='NaN',metadata=dict(sample_id=3,epoch=1)))
    row=dict(activation=7,locals=dict(scorer_name='scorer_a',scores=[item],reduced_scores=[item]))
    raw=facts('raw-input',row,'test')[0]
    reduced=facts('reduced-input',row,'test')[0]
    assert raw['values']['raw']==reduced['values']['raw']=='NaN'
    assert raw['identity']['epoch']==1 and reduced['identity']['epoch']==0
    assert raw['identity']['activation']==reduced['identity']['activation']==7


@pytest.mark.parametrize('case,raw_a', [(dict(id='a-before-b',order=['a','b']),6),(dict(id='b-before-a',order=['b','a']),5)])
def test_prospective_membership_retains_final_only_activations_and_source_order(case,raw_a):
    expected=decl.expected_site_identities(case,'run')
    assert len(expected['score-commit'])==len(expected['raw-consumer'])==raw_a+4
    assert {i['activation'] for i in expected['classification-count']}=={2,3,5,6}
    assert expected['metric-empty-input']==[]
    assert {i['activation'] for i in expected['metric-nonempty-input']}=={2,3,5,6}
    assert len(expected['classification-input'])==raw_a+4+6
    assert all(i['epoch']==0 for i in expected['reduced-input'])
    rows=decl.case_inventory(case,'run')
    assert len({tuple(sorted(i.items())) for i in rows})==len(rows)
    assert all(i in rows for identities in expected.values() for i in identities)


def test_no_call_controls_have_no_fabricated_membership():
    case=dict(id='no-native-call',order=[])
    assert decl.case_inventory(case,'run')==[]
    assert all(v==[] for v in decl.expected_site_identities(case,'run').values())


def test_all_none_native_control_qualifies_empty_branch_without_fake_scores():
    expected=decl.expected_site_identities(dict(id='empty-scoring',order=['a','b'],empty_scores=True),'run')
    assert expected['score-commit']==expected['raw-consumer']==expected['classification-input']==[]
    assert {i['activation'] for i in expected['metric-empty-input']}=={2,3,5,6}
    assert expected['metric-nonempty-input']==[]


def test_integrity_loader_executes_original_namespace_packages(tmp_path):
    from inspect_path.native_driver import source_inventory,load_native
    import subprocess
    files={'inspect_ai/__init__.py':'from ._eval.task import results\n',
           'inspect_ai/_eval/task/results.py':'original_value = 73\n',
           'inspect_ai/_eval/task/run.py':'from .results import original_value\n',
           'inspect_ai/scorer/_metric.py':'class Score: pass\nclass SampleScore: pass\n',
           'inspect_ai/lazy/nested.py':'pinned_value=82\n'}
    for name,source in files.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
    command="import sys;sys.path.insert(0,sys.argv[1]);from native_driver import load_native,source_inventory;n=load_native(sys.argv[2],source_inventory(sys.argv[2]));assert n[0].results.original_value==73;from pathlib import Path;Path(sys.argv[2]+'/inspect_ai/lazy/nested.py').write_text('pinned_value=83\\n');import inspect_ai.lazy.nested"
    proc=subprocess.run([sys.executable,'-I','-c',command,str(VALIDATION/'inspect_path'),str(tmp_path)],capture_output=True,text=True)
    assert proc.returncode!=0 and 'Native source changed during import' in proc.stderr,proc.stderr


def test_integrity_loader_refuses_changed_original_namespace_module(tmp_path):
    from inspect_path.native_driver import source_inventory,load_native
    path=tmp_path/'inspect_ai/no_initializer/module.py';path.parent.mkdir(parents=True);path.write_text('x=1\n')
    inventory=source_inventory(tmp_path)
    path.write_text('x=2\n')
    with pytest.raises(ValueError,match='inventory changed'):load_native(tmp_path,inventory)


def test_reference_selects_actual_async_statement_entry_not_cleanup_line(tmp_path):
    import asyncio
    from inspect_path.reference import source_points,point_rows
    source='''async def f(value):
    results = {}
    async with context():
        if value is not None:
            results["score"] = dict(
                value=value,
            )
    return results
'''
    path=tmp_path/'native.py';path.write_text(source)
    class Context:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return None
    namespace={'context':Context}
    exec(compile(source,str(path),'exec'),namespace)
    points=source_points(tmp_path,'native.py','f','results["score"] = dict(value=value)')
    for value in [None,7]:
        rows=[]
        def trace(frame,event,arg):
            if frame.f_code is namespace['f'].__code__ and event in ['line','return','exception']:
                rows.append(dict(call=1,path='native.py',function='f',event=event,line=frame.f_lineno,offset=frame.f_lasti,
                                 locals=copy.deepcopy({k:v for k,v in frame.f_locals.items() if k in ['value','results']})))
            return trace
        sys.settrace(trace)
        try:returned=asyncio.run(namespace['f'](value))
        finally:sys.settrace(None)
        before=list(point_rows(rows,'native.py','f',points,'before'))
        after=list(point_rows(rows,'native.py','f',points,'after'))
        assert len(before)==len(after)==(0 if value is None else 1)
        if after:assert after[0]['locals']['results']==returned=={'score':{'value':7}}


def test_fault_controls_change_both_retained_journal_and_semantic_view():
    from inspect_path.campaign import mutation_journal
    original=dict(batch_journal=[{'schema':'begin'}, {'id':'1','values':{'raw':'NaN'}},
                                {'id':'2','values':{'raw':'1.0'}},{'schema':'end'}],transport={'1':True})
    changed=[{'id':'2','values':{'raw':'corrupted'}}]
    result=mutation_journal(changed,original)
    assert result['batch_journal']==[{'schema':'begin'},changed[0],{'schema':'end'}]
    assert result['transport']=={'1':True}
    assert len(original['batch_journal'])==4 and original['batch_journal'][2]['values']['raw']=='1.0'
