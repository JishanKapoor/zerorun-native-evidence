import copy
import math
import sys
from types import ModuleType
import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding,recorder
from zerorun_harness.projection import project,validate_projection
from zerorun_harness.records import register_records
from zerorun_harness._telemetry_protocol import PrimitiveError
from test_native_projection import one_site


MODEL='''class Score:
    value: float
    def __init__(self,value):
        self.value=value
'''
NATIVE='def outer(score):\n result = score\n return result\n'
SPEC={'local':'score','path':[{'stored':'value','record':'score'}],'encoding':'number_json'}


def prepared(monkeypatch,source=MODEL):
    p=one_site('outer','result = score','after',SPEC)
    p['facts']['raw']['flag']='str'
    p['record_types']={'score':{'module':'native_model','name':'Score','path':'native_model.py','fields':['value']}}
    sources={'native.py':NATIVE,'native_model.py':source}
    b=generate_binding(p,sources,grammar_version='1.3.0')
    module=ModuleType('native_model');exec(source,module.__dict__)
    monkeypatch.setitem(sys.modules,'native_model',module)
    registry=register_records(p,b,{'score':module.Score})
    return p,b,module,registry


@pytest.mark.parametrize('value,expected',[(1,'1'),(1.5,'1.5'),(-0.0,'-0.0'),(math.nan,'NaN'),(math.inf,'Infinity'),(-math.inf,'-Infinity')])
def test_exact_native_numeric_dispositions_remain_distinct(monkeypatch,value,expected):
    p,b,module,registry=prepared(monkeypatch)
    score=module.Score(value)
    assert project(SPEC,{'score':score},records=registry)==expected
    seen=[]
    class Sink:
        def emit(self,event):seen.append(event);return True
    callback=recorder(p,b,Sink(),123,records=registry)
    assert callback('return',{'score':score}) is True
    assert seen[0]['values']['flag']==expected


def test_registered_read_bypasses_custom_native_attribute_hook(monkeypatch):
    source=MODEL+'''    def __getattribute__(self,key):
        raise AssertionError('attribute hook must not execute')
'''
    _,_,module,registry=prepared(monkeypatch,source)
    assert project(SPEC,{'score':module.Score(7)},records=registry)=='7'


def test_runtime_registry_and_caller_declarations_cannot_be_retargeted(monkeypatch):
    p,b,module,registry=prepared(monkeypatch)
    p['record_types']['score']['fields'].append('other')
    with pytest.raises(PrimitiveError):registry.read(module.Score(7),'score','other')
    with pytest.raises(AttributeError):registry._records={}
    with pytest.raises(AttributeError):registry.binding_sha256='x'


def test_binding_rejects_registry_from_different_profile(monkeypatch):
    p,b,module,registry=prepared(monkeypatch);p['id']='other'
    new=generate_binding(p,b['original'],grammar_version='1.3.0')
    with pytest.raises(InvalidEvidence,match='source-matched'):recorder(p,new,object(),123,records=registry)


@pytest.mark.parametrize('mutation',['property','getattribute','module'])
def test_mutated_registered_class_is_refused_without_dispatch(monkeypatch,mutation):
    _,_,module,registry=prepared(monkeypatch);value=module.Score(7);called=[]
    if mutation=='property':monkeypatch.setattr(module.Score,'value',property(lambda s:called.append(1) or 9),raising=False)
    elif mutation=='getattribute':monkeypatch.setattr(module.Score,'__getattribute__',lambda *a:called.append(1),raising=False)
    else:monkeypatch.setattr(module.Score,'__module__','changed')
    with pytest.raises(PrimitiveError):project(SPEC,{'score':value},records=registry)
    assert called==[]


def test_subclass_and_absent_storage_refused(monkeypatch):
    _,_,module,registry=prepared(monkeypatch)
    class Derived(module.Score):pass
    with pytest.raises(PrimitiveError):project(SPEC,{'score':Derived(7)},records=registry)
    value=module.Score(7);del value.value
    with pytest.raises(PrimitiveError):project(SPEC,{'score':value},records=registry)


def test_custom_dictionary_descriptor_is_never_invoked(monkeypatch):
    source=MODEL+'''    @property
    def __dict__(self):
        raise AssertionError('dictionary property must not run')
'''
    with pytest.raises(InvalidEvidence,match='instance dictionary'):prepared(monkeypatch,source)


def test_computed_field_is_not_mislabeled_stored(monkeypatch):
    source='''class Score:
    value: float
    @property
    def value(self):raise AssertionError('property')
'''
    with pytest.raises(InvalidEvidence,match='stored'):prepared(monkeypatch,source)


@pytest.mark.parametrize('value',[True,None,'NaN',[],{},object()])
def test_numeric_wire_never_coerces_arbitrary_values(value):
    with pytest.raises(PrimitiveError):project({'local':'x','encoding':'number_json'},{'x':value})


@pytest.mark.parametrize('version',['1.0.0','1.1.0','1.2.0'])
def test_stored_fields_and_nonfinite_tokens_require_explicit_new_grammar(monkeypatch,version):
    p,b,_,_=prepared(monkeypatch)
    with pytest.raises(InvalidEvidence,match='Old grammar'):generate_binding(p,b['original'],grammar_version=version)


def test_unregistered_stored_field_never_uses_property_fallback():
    class Score:
        @property
        def value(self):raise AssertionError('property must not run')
    validate_projection(SPEC)
    with pytest.raises(PrimitiveError):project(SPEC,{'score':Score()})


def test_native_source_requires_actual_annotated_class_field(monkeypatch):
    p,b,_,_=prepared(monkeypatch)
    sources=copy.deepcopy(b['original']);sources['native_model.py']=MODEL.replace('    value: float\n','')
    with pytest.raises(InvalidEvidence,match='annotated'):generate_binding(p,sources,grammar_version='1.3.0')
