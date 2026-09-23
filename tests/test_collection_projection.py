"""Finite native collection facts must never invoke arbitrary Python hooks."""
import multiprocessing as mp

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness._telemetry_protocol import PrimitiveError
from zerorun_harness.projection import project, validate_projection


@pytest.mark.parametrize('value',[[],(),{},set(),[1,2],(1,2),{'a':1,'b':2},{'a','b'}])
def test_native_size(value):
    spec={'local':'x','size':True}
    validate_projection(spec)
    assert project(spec,{'x':value})==len(value)


@pytest.mark.parametrize('lock',[mp.Lock,mp.RLock])
def test_native_shared_array_size(lock):
    value=mp.Array('i',[1,2,3],lock=lock())
    assert project({'local':'x','size':True},{'x':value})==3


@pytest.mark.parametrize('value',[['a','b'],('a','b'),{'a':1,'b':2},{'a','b'}])
@pytest.mark.parametrize('needle,expected',[('a',True),('c',False)])
def test_membership(value,needle,expected):
    spec={'local':'x','contains':{'local':'needle'}}
    validate_projection(spec)
    assert project(spec,{'x':value,'needle':needle}) is expected


def test_literal_membership_and_set_encoding():
    assert project({'local':'x','contains':{'literal':2}},{'x':{1,2}}) is True
    for value,expected in [({'b','a'},'["a","b"]'),({10,2},'[2,10]'),(set(),'[]')]:
        spec={'local':'x','encoding':'sorted_json'}
        validate_projection(spec)
        assert project(spec,{'x':value})==expected


@pytest.mark.parametrize('suffix',[
    {'size':1},{'size':False},{'contains':{'literal':True}},
    {'contains':{'local':'__zr_hidden'}},{'contains':{'call':'f'}},
    {'size':True,'encoding':'json'}, {'size':True,'contains':{'literal':'a'}},
    {'contains':{'literal':'a'},'encoding':'json'},
])
def test_invalid_collection_declarations(suffix):
    with pytest.raises(InvalidEvidence):validate_projection({'local':'x',**suffix})


def test_custom_collection_hooks_are_never_called():
    called=[]
    class Custom(list):
        def __len__(self):called.append('len');return 1
        def __contains__(self,value):called.append('contains');return True
    for spec in [{'local':'x','size':True},{'local':'x','contains':{'literal':'a'}}]:
        with pytest.raises(PrimitiveError):project(spec,{'x':Custom(['a'])})
    assert called==[]


def test_custom_membership_keys_and_selectors_never_dispatch():
    called=[]
    class Key:
        def __hash__(self):return hash('a')
        def __eq__(self,other):called.append('eq');return True
    for container in [[Key()],{Key()}]:
        called.clear()
        with pytest.raises(PrimitiveError):project({'local':'x','contains':{'literal':'a'}},{'x':container})
        assert called==[]
    with pytest.raises(PrimitiveError):project({'local':'x','contains':{'local':'n'}},{'x':{'a'},'n':Key()})
    assert called==[]


def test_collection_bounds_and_type_refusals():
    for container in [set(range(4097)),list(range(4097))]:
        with pytest.raises(PrimitiveError):project({'local':'x','contains':{'literal':0}},{'x':container})
    for value in [{'a',1},{1.0},{True},set(range(65))]:
        with pytest.raises(PrimitiveError):project({'local':'x','encoding':'sorted_json'},{'x':value})
