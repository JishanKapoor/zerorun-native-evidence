import copy
import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding,recorder
from zerorun_harness.batches import extract_batches
from test_native_projection import one_site


SOURCE='def outer(details):\n native = details[:]\n return native\n'


def acquired(values):
    p=one_site('outer','native = details[:]','after',{'item':True})
    p['sites']['return'].update(batch={'local':'native','max_items':64})
    p['sites']['return']['projection']['obligation']={'ordinal':True}
    b=generate_binding(p,{'native.py':SOURCE});raw=[]
    class Sink:
        def emit(self,value):raw.append(copy.deepcopy(value));return True
    scope={'__zr_observe':recorder(p,b,Sink(),321)}
    exec(b['transformed']['native.py'],scope)
    result=scope['outer'](values)
    return p,b,raw,result


@pytest.mark.parametrize('values',[[],[1],[0,1],[1]*64])
def test_actual_materialized_population_and_zero_batch(values):
    p,b,raw,result=acquired(values)
    a=extract_batches(p,b,raw)
    assert result==values and result is not values
    assert [e['values']['flag'] for e in a['events']]==values
    assert [e['identity']['obligation'] for e in a['events']]==list(range(len(values)))
    assert len(a['batches'])==1 and a['batches'][0]['complete'] is True
    assert a['batches'][0]['size']==len(values)


@pytest.mark.parametrize('remove',['end','element'])
def test_lost_batch_parts_cannot_establish_complete_inventory(remove):
    p,b,raw,_=acquired([1,1])
    del raw[-1 if remove=='end' else 1]
    a=extract_batches(p,b,raw)
    assert a['batches'][0]['complete'] is False


def test_duplicate_or_wrong_ordinal_cannot_establish_population():
    p,b,raw,_=acquired([1,1]);raw[2]['identity']['obligation']=0
    assert extract_batches(p,b,raw)['batches'][0]['complete'] is False


@pytest.mark.parametrize('change',['size','binding','pid','site','begin','repeat','missing-begin'])
def test_batch_provenance_ambiguity_refused(change):
    p,b,raw,_=acquired([1])
    if change=='size':raw[-1]['size']=2
    elif change=='binding':raw[-1]['binding_sha256']='0'*64
    elif change=='pid':raw[-1]['producer']=99
    elif change=='site':raw[-1]['site']='other'
    elif change=='begin':raw.insert(1,copy.deepcopy(raw[0]))
    elif change=='repeat':raw.extend(copy.deepcopy(raw))
    else:del raw[0]
    with pytest.raises(InvalidEvidence):extract_batches(p,b,raw)


def test_batch_rejects_custom_sequence_without_hook_dispatch():
    p,b,_,_=acquired([1]);called=[]
    class Custom(list):
        def __iter__(self):called.append('iter');return iter([7])
        def __len__(self):called.append('len');return 1
    class Sink:
        def emit(self,event):return type(event) is dict
    cb=recorder(p,b,Sink(),321)
    assert cb('return',{'native':Custom([1])}) is False
    assert called==[]


def test_oversized_native_batch_is_rejected_without_partial_enumeration():
    p,b,_,_=acquired([1]);seen=[]
    class Sink:
        def emit(self,event):seen.append(event);return type(event) is dict
    assert recorder(p,b,Sink(),321)('return',{'native':[1]*65}) is False
    assert len(seen)==1 and type(seen[0]) is object


@pytest.mark.parametrize('version',['1.0.0','1.1.0'])
def test_native_batch_requires_new_binding_grammar(version):
    p,_,_,_=acquired([1])
    with pytest.raises(InvalidEvidence,match='Old grammar'):
        generate_binding(p,{'native.py':SOURCE},grammar_version=version)


def test_partial_emission_still_attempts_all_actual_elements_and_seal():
    p,b,_,_=acquired([1]);seen=[]
    class Sink:
        def emit(self,event):seen.append(event);return len(seen)!=2
    assert recorder(p,b,Sink(),321)('return',{'native':[1,0]}) is False
    assert len(seen)==4 and seen[-1]['stage']=='end'
    assert seen[2]['values']['flag']==0


def test_declared_large_bank_is_streamed_without_wire_container_truncation():
    p,_,_,_=acquired([1]);p['sites']['return']['batch']['max_items']=4096
    b=generate_binding(p,{'native.py':SOURCE});seen=[]
    class Sink:
        def emit(self,event):seen.append(copy.deepcopy(event));return True
    assert recorder(p,b,Sink(),321)('return',{'native':list(range(4096))}) is True
    result=extract_batches(p,b,seen)
    assert result['batches'][0]['complete'] is True
    assert result['batches'][0]['size']==4096
    assert [e['values']['flag'] for e in result['events']]==list(range(4096))
    assert len(seen)==4098


def test_unbounded_batch_declaration_is_refused():
    p,_,_,_=acquired([1]);p['sites']['return']['batch']['max_items']=4097
    with pytest.raises(InvalidEvidence):generate_binding(p,{'native.py':SOURCE})
