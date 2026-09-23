import asyncio
import copy
import sys
import types

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.records import register_records
from test_native_projection import one_site


def observe(source, *, function='Native.method', anchor='value = n', position='after', projection=None, activation=False):
    p = one_site(function, anchor, position, projection or {'local':'value'})
    if activation:p['sites']['return']['projection']['obligation']={'activation':True}
    b = generate_binding(p, {'native.py': source}, grammar_version='1.4.0')
    events=[]
    class Sink:
        def emit(self, value):events.append(copy.deepcopy(value));return type(value) is dict
    callback=recorder(p,b,Sink(),123)
    scope={'__zr_observe__':callback}
    exec(b['transformed']['native.py'],scope)
    return p,b,events,scope


def test_instance_method_has_unmangled_callback_and_preserves_docstring():
    source='class Native:\n def method(self,n):\n  "native doc"\n  value = n\n  return value\n'
    _,_,events,scope=observe(source,activation=True)
    assert scope['Native']().method(7)==7
    assert scope['Native'].method.__doc__=='native doc'
    assert events[0]['values']['flag']==7 and events[0]['identity']['obligation']==1


@pytest.mark.parametrize('kind,arg', [('staticmethod',''),('classmethod','cls,')])
def test_ordinary_method_decorators_remain_native(kind,arg):
    source=f'class Native:\n @{kind}\n def method({arg}n):\n  value = n\n  return value\n'
    _,_,events,scope=observe(source)
    assert scope['Native'].method(4)==4 and events[0]['values']['flag']==4


def test_nested_class_return_is_evaluated_once_and_zero_arg_super_preserved():
    source='''class Parent:
 def value(self,n): return n+1
class Outer:
 class Native(Parent):
  def method(self,n):
   return super().value(n)
'''
    _,_,events,scope=observe(source,function='Outer.Native.method',anchor='return super().value(n)',
                              position='return_value',projection={'return':True})
    assert scope['Outer'].Native().method(5)==6 and events[0]['values']['flag']==6


def test_async_method_actual_activation_and_return_survive_await():
    source='import asyncio\nclass Native:\n async def method(self,n):\n  await asyncio.sleep(0)\n  return n\n'
    _,_,events,scope=observe(source,anchor='return n',position='return_value',projection={'return':True},activation=True)
    assert asyncio.run(scope['Native']().method(8))==8
    assert events[0]['values']['flag']==8 and events[0]['identity']['obligation']==1


@pytest.mark.parametrize('version',['1.0.0','1.1.0','1.2.0','1.3.0'])
def test_old_grammars_keep_method_refusal(version):
    p=one_site('Native.method','value = n','after',{'local':'value'})
    with pytest.raises(InvalidEvidence):
        generate_binding(p,{'native.py':'class Native:\n def method(self,n):\n  value = n\n'},grammar_version=version)


@pytest.mark.parametrize('name',['__zr_observe__','__zr_return__','__zr_activation__'])
def test_unmangled_plumbing_cannot_be_shadowed(name):
    source=f'{name}=None\nclass Native:\n def method(self,n):\n  value = n\n'
    with pytest.raises(InvalidEvidence):observe(source)


def test_selector_cannot_end_at_class_or_resolve_ambiguous_scope():
    p=one_site('Native','value = n','after',{'local':'value'})
    with pytest.raises(InvalidEvidence):
        generate_binding(p,{'native.py':'class Native:\n value = n\n'},grammar_version='1.4.0')
    with pytest.raises(InvalidEvidence):
        observe('class Native:\n def method(self,n):\n  value = n\nclass Native: pass\n')


def test_method_local_introspection_still_refused():
    with pytest.raises(InvalidEvidence):
        observe('class Native:\n def method(self,n):\n  value = n\n  return locals()\n',activation=True)


def test_return_temporary_cannot_change_finally_local_introspection():
    source='class Native:\n def method(self,n):\n  try:\n   return n\n  finally:\n   n.append(sorted(locals()))\n'
    with pytest.raises(InvalidEvidence):
        observe(source,anchor='return n',position='return_value',projection={'return':True})


def record_profile():
    p=one_site('read','value = record','after',
               {'local':'record','path':[{'record':'report','stored':'value'}]})
    p['record_types']={'report':{'module':'native','name':'Report','path':'native.py','fields':['value']}}
    return p


def test_same_source_inherited_annotation_with_exact_actual_storage():
    source='class Base:\n value:int\nclass Report(Base):\n def __init__(self,value):self.value=value\ndef read(record):\n value = record\n return value\n'
    p=record_profile()
    with pytest.raises(InvalidEvidence):generate_binding(p,{'native.py':source},grammar_version='1.3.0')
    b=generate_binding(p,{'native.py':source},grammar_version='1.4.0')
    native=types.ModuleType('native');sys.modules['native']=native
    events=[]
    class Sink:
        def emit(self,value):events.append(value);return True
    try:
        exec(b['transformed']['native.py'],native.__dict__)
        registry=register_records(p,b,{'report':native.Report})
        native.__zr_observe__=recorder(p,b,Sink(),123,records=registry)
        value=native.Report(3)
        assert native.read(value) is value
        assert events[0]['values']['flag']==3
    finally:sys.modules.pop('native',None)


def test_direct_initializer_annotation_admitted_only_in_new_grammar():
    source='class Report:\n def __init__(self,value):\n  self.value:int=value\ndef read(record):\n value = record\n'
    p=record_profile()
    with pytest.raises(InvalidEvidence):generate_binding(p,{'native.py':source},grammar_version='1.3.0')
    assert generate_binding(p,{'native.py':source},grammar_version='1.4.0')['grammar_version']=='1.4.0'


@pytest.mark.parametrize('initializer',[
    'def __init__(self):\n  def nested(self):\n   self.value:int=1',
    'def __init__(self,other):\n  other.value:int=1',
    '@staticmethod\n def __init__(self):\n  self.value:int=1',
    'def __init__(self):\n  self.value=1'])
def test_unqualified_initializer_field_routes_refused(initializer):
    source='class Report:\n '+initializer+'\ndef read(record):\n value = record\n'
    with pytest.raises(InvalidEvidence):generate_binding(record_profile(),{'native.py':source},grammar_version='1.4.0')


@pytest.mark.parametrize('source',[
    'from unknown import Base\nclass Report(Base):pass\ndef read(record):\n value = record\n',
    'class Base(Report):pass\nclass Report(Base):pass\ndef read(record):\n value = record\n',
    'class Base:\n value:int\nclass Base:pass\nclass Report(Base):pass\ndef read(record):\n value = record\n'])
def test_missing_cyclic_or_ambiguous_inherited_fields_refused(source):
    with pytest.raises(InvalidEvidence):generate_binding(record_profile(),{'native.py':source},grammar_version='1.4.0')
