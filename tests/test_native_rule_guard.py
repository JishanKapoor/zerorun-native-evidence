import copy
import pytest

from zerorun_harness.api import InvalidEvidence,digest
from zerorun_harness.binding import generate_binding,recorder
from zerorun_harness.batches import extract_batches
from zerorun_harness.declarative import evaluate
from test_complete_batch_policy import SOURCE,run_case


def fixture(raw=0,values=None):
    if values is None:values=[]
    p,_,case,_,health,_=run_case(values)
    p['facts']['state']={'raw':'int'}
    s=copy.deepcopy(p['sites']['grade']);s.update(kind='state',anchor='state = raw')
    s['projection'].pop('accepted');s['projection']['raw']={'local':'state'}
    p['sites']['state']=s
    p['rules'][0]['guard']={'kind':'state','field':'raw','in':[0]}
    p['rules'][0]['requires'].append('state')
    source=SOURCE.replace('details,expected','details,expected,raw').replace('    native =','    state = raw\n    native =')
    b=generate_binding(p,{'native.py':source});payloads=[]
    class Sink:
        def emit(self,e):payloads.append(copy.deepcopy(e));return True
    scope={'__zr_observe':recorder(p,b,Sink(),321)};exec(b['transformed']['native.py'],scope)
    scope['outer'](values,2,raw)
    acq=extract_batches(p,b,payloads)
    case['source_sha256']=digest(b['original_sources'])
    health.update(binding_sha256=b['sha256'],batch_journal=payloads,sites={s:True for s in p['sites']})
    return p,b,case,acq['events'],health


def row(parts):
    p,b,c,events,h=parts
    return evaluate(p,c,events,h,b['sha256'])['records'][0]


@pytest.mark.parametrize('raw',[1,2,3])
@pytest.mark.parametrize('values',[[],[1],[1,1]])
def test_known_native_state_excludes_unrelated_conjunction_branch(raw,values):
    result=row(fixture(raw,values))
    assert result['status']=='CONFORMS'
    assert result['reasons']==['native_rule_guard_not_applicable']


@pytest.mark.parametrize('values',[[],[1],[1,1],[0,1]])
def test_native_success_guard_uses_actual_batch_conjunction(values):
    result=row(fixture(0,values))
    assert result['status']=='CONFORMS' and result['reasons']==[]


@pytest.mark.parametrize('mutation',['missing','duplicate','unqualified','transport','completion'])
def test_unproved_guard_cannot_make_the_branch_conform(mutation):
    parts=fixture(1);events=parts[3];h=parts[4]
    if mutation=='missing':
        events[:]=[e for e in events if e['kind']!='state']
        h['batch_journal']=[e for e in h['batch_journal'] if e.get('kind')!='state']
    elif mutation=='duplicate':
        duplicate=copy.deepcopy(next(e for e in events if e['kind']=='state'))
        duplicate.update(id='321:999',seq=999);events.append(duplicate)
    elif mutation=='unqualified':h['sites']['state']=False
    elif mutation=='transport':h['transport']['321']=False
    else:h['native_complete'][parts[0]['rules'][0]['id']]=False
    assert row(parts)['status']=='INCONCLUSIVE'


def test_guard_witness_is_retained_in_evidence_ids():
    parts=fixture(1)
    assert next(e['id'] for e in parts[3] if e['kind']=='state') in row(parts)['evidence_ids']


@pytest.mark.parametrize('bad',[{'kind':'missing','field':'raw','in':[0]},
                              {'kind':'state','field':'missing','in':[0]},
                              {'kind':'state','field':'raw','in':[True]},
                              {'kind':'state','field':'raw','in':[]},
                              {'kind':'state','field':'raw','in':[0],'call':'predicate'}])
def test_guard_is_finite_typed_native_membership_only(bad):
    parts=fixture();parts[0]['rules'][0]['guard']=bad
    with pytest.raises(InvalidEvidence):row(parts)
