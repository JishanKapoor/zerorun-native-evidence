import copy
import pytest

from zerorun_harness.api import digest,InvalidEvidence
from zerorun_harness.binding import generate_binding,recorder
from zerorun_harness.batches import extract_batches
from zerorun_harness.declarative import evaluate
from test_native_projection import one_site


SOURCE='''def outer(details,expected):
    native = details[:]
    accepted = len(native) == expected and all(native)
    return accepted
'''


def run_case(values,expected=2,*,policy=True):
    p=one_site('outer','native = details[:]','after',{'item':True})
    site=p['sites']['return'];site['batch']={'local':'native','max_items':64}
    site['projection']['obligation']={'ordinal':True}
    target=copy.deepcopy(site);target.pop('batch');target.update(kind='grade',anchor='accepted = len(native) == expected and all(native)')
    target['projection']['obligation']={'literal':0};target['projection'].pop('flag');target['projection']['accepted']={'local':'accepted'}
    p['sites']['grade']=target;p['facts']['grade']={'accepted':'bool'}
    r=p['rules'][0];r.update(check='C3',consumer='grade',keys=[k for k in p['identity'] if k!='obligation'],
                            target_field='accepted',operator='all_in',statuses=[1],requires=['return','grade'])
    if policy:r['inventory_policy']='complete_batch_membership'
    b=generate_binding(p,{'native.py':SOURCE});raw=[]
    class Sink:
        def emit(self,value):raw.append(copy.deepcopy(value));return True
    scope={'__zr_observe':recorder(p,b,Sink(),321)};exec(b['transformed']['native.py'],scope)
    actual=scope['outer'](values,expected);acq=extract_batches(p,b,raw)
    identity=dict(run='r',candidate='c',phase='b',attempt=1)
    case=dict(id='authored-batch-control',version='1',inventory=[dict(identity,obligation=i) for i in range(expected)],
              source_sha256=digest(b['original_sources']),input_sha256=digest(values))
    h=dict(binding_sha256=b['sha256'],sites={k:True for k in p['sites']},transport={'321':True},
           native_complete={r['id']:True},qualification_sha256='1'*64)
    if policy:h['batch_journal']=raw
    return p,b,case,acq['events'],h,actual


def verdict(parts):
    p,b,c,events,h,*_=parts
    return evaluate(p,c,events,h,b['sha256'])['records'][0]['status']


@pytest.mark.parametrize('values,expected',[( [],False),([1],False),([1,1],True),([1,0],False),([0],False)])
def test_actual_complete_batch_proves_length_membership_and_conjunction(values,expected):
    parts=run_case(values)
    assert parts[-1] is expected
    assert verdict(parts)=='CONFORMS'


@pytest.mark.parametrize('values',[[],[1],[1,1],[1,0],[0]])
def test_wrong_native_grade_contradicts_retained_complete_population(values):
    parts=run_case(values)
    grade=next(e for e in parts[3] if e['kind']=='grade')
    grade['values']['accepted']=not grade['values']['accepted']
    # Retained journal includes actual same received event, for an authored
    # corrupt-output control; never change a real retained native journal.
    next(e for e in parts[4]['batch_journal'] if e.get('kind')=='grade')['values']['accepted']=grade['values']['accepted']
    assert verdict(parts)=='VIOLATION'


@pytest.mark.parametrize('loss',['end','transport','completion','qualification'])
def test_missing_premise_cannot_turn_short_true_list_into_known_native_failure(loss):
    parts=run_case([1]);h=parts[4]
    if loss=='end':h['batch_journal']=[x for x in h['batch_journal'] if x.get('stage')!='end' and x.get('kind')!='grade']
    elif loss=='transport':h['transport']['321']=False
    elif loss=='completion':h['native_complete'][parts[0]['rules'][0]['id']]=False
    else:h['sites']['return']=False
    assert verdict(parts)=='INCONCLUSIVE'


def test_old_policy_keeps_missing_all_true_inputs_unknown():
    assert verdict(run_case([1],policy=False))=='INCONCLUSIVE'


def test_batch_journal_cannot_disagree_with_retained_events():
    parts=run_case([1,1]);parts[4]['batch_journal'][1]['values']['flag']=0
    with pytest.raises(InvalidEvidence,match='disagrees'):verdict(parts)


def test_batch_group_cannot_be_reassigned_to_another_candidate():
    parts=run_case([])
    for x in parts[4]['batch_journal']:
        if x.get('schema')=='zerorun-native-batch/1':x['identity']['candidate']='other'
    assert verdict(parts)=='INCONCLUSIVE'
