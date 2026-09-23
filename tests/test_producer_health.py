import copy
import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding
from zerorun_harness.declarative import evaluate,validate_profile
from declarative_support import SOURCE,execute


def fixture():
    p,b,c,events,h,result=execute([True])
    for site,spec in p['sites'].items():
        spec['producer_role']='parent' if site in ('serialize','aggregate') else 'worker'
    # Parent-local self-preservation isolates unrelated worker loss.
    rule=copy.deepcopy(p['rules'][2])
    rule.update(id='parent-local',producer='serialized',source_field='flag',operator='identity',requires=['serialize'])
    p['rules'].append(rule)
    b=generate_binding(p,{'native.py':SOURCE})
    for event in events:
        event.update(binding_sha256=b['sha256'],producer=11 if p['sites'][event['site']]['producer_role']=='parent' else 22)
        event['id']=str(event['producer'])+':'+str(event['seq'])
    h.update(binding_sha256=b['sha256'],transport={'11':True,'22':True},
             producers={'parent':11,'worker':22})
    h['native_complete']['parent-local']=True
    return p,b,c,events,h


def assess(parts):
    p,b,c,events,h=parts
    return evaluate(p,c,events,h,b['sha256'])


@pytest.mark.parametrize('worker_health',[False,None])
def test_unrelated_worker_loss_preserves_parent_local_conclusion(worker_health):
    parts=fixture();parts[4]['transport']['22']=worker_health
    rows={r['relationship']:r['status'] for r in assess(parts)['records']}
    assert rows['parent-local']=='CONFORMS'
    assert rows['commit-required']=='INCONCLUSIVE'
    assert rows['serialization-preserved']=='INCONCLUSIVE'


def test_killed_worker_cannot_create_missing_commit_violation():
    parts=fixture();parts[4]['transport']['22']=False
    parts[3][:]=[e for e in parts[3] if e['site']!='commit']
    assert next(r for r in assess(parts)['records'] if r['relationship']=='commit-required')['status']=='INCONCLUSIVE'


def test_witnessed_worker_contradiction_remains():
    parts=fixture();parts[4]['transport']['22']=False
    next(e for e in parts[3] if e['site']=='commit')['values']['stored']=False
    assert next(r for r in assess(parts)['records'] if r['relationship']=='decision-preserved')['status']=='VIOLATION'


@pytest.mark.parametrize('mutation',['wrong-pid','same-pid','missing-role','missing-transport','unresolved-with-events'])
def test_role_ambiguity_refused(mutation):
    parts=fixture();h=parts[4]
    if mutation=='wrong-pid':parts[3][0]['producer']=11
    elif mutation=='same-pid':h['producers']['worker']=11
    elif mutation=='missing-role':del h['producers']['worker']
    elif mutation=='missing-transport':del h['transport']['22']
    else:h['producers']['worker']=None
    with pytest.raises(InvalidEvidence):assess(parts)


def test_unresolved_worker_without_events_leaves_parent_supported():
    parts=fixture();parts[4]['producers']['worker']=None
    parts[3][:]=[e for e in parts[3] if e['producer']==11]
    result=assess(parts)
    assert result['engine_version']=='1.1.0'
    assert next(r for r in result['records'] if r['relationship']=='parent-local')['status']=='CONFORMS'


def test_partial_site_role_declaration_refused():
    parts=fixture();del parts[0]['sites']['accept']['producer_role']
    with pytest.raises(InvalidEvidence,match='every site'):validate_profile(parts[0])
