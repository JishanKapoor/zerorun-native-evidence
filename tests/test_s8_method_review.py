"""Independent finite grammar 1.4 admission and native preservation controls."""
import asyncio
import sys
import types

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.records import register_records
from test_method_binding import observe, record_profile
from test_native_projection import one_site


@pytest.mark.parametrize('expression,imports', [
    ('dir()', ''),
    ('builtins.dir()', 'import builtins\n'),
    ('capture()', 'from builtins import dir as capture\n'),
    ('second()', 'capture = dir\nsecond = capture\n'),
])
def test_zero_argument_dir_is_local_introspection(expression, imports):
    source = imports + ('class Native:\n def method(self,n):\n'
                        f'  captured = {expression}\n  value = n\n  return captured\n')
    with pytest.raises(InvalidEvidence, match='introspection'):
        observe(source, activation=True)


def test_dir_on_explicit_object_preserves_native_behavior():
    source = 'class Native:\n def method(self,n):\n  names=dir(n)\n  value = n\n  return names\n'
    _, _, events, scope = observe(source, activation=True)
    assert scope['Native']().method(1) == dir(1)
    assert events[0]['values']['flag'] == 1


def test_return_capture_cannot_change_finally_zero_argument_dir():
    source = ('class Native:\n def method(self,n):\n  try:\n   return n\n'
              '  finally:\n   n.append(dir())\n')
    with pytest.raises(InvalidEvidence, match='introspection'):
        observe(source, anchor='return n', position='return_value', projection={'return':True})


@pytest.mark.parametrize('rebind', [
    'Base = object',
    'from builtins import object as Base',
    'if True:\n Base = object',
    'for Base in [object]:\n pass',
    'try:\n raise RuntimeError()\nexcept RuntimeError as Base:\n pass\nBase=object',
    'match object:\n case Base:\n  pass',
    'def unused(argument:(Base:=object)):pass',
    'unused = lambda argument=(Base:=object):None',
])
def test_inherited_annotation_cannot_come_from_a_shadowed_source_base(rebind):
    source = ('class Base:\n value:int\n' + rebind + '\nclass Report(Base):\n'
              ' def __init__(self,value):self.value=value\n'
              'def read(record):\n value = record\n')
    with pytest.raises(InvalidEvidence):
        generate_binding(record_profile(), {'native.py':source}, grammar_version='1.4.0')


def test_decorated_source_base_cannot_supply_unwitnessed_inherited_annotation():
    source = ('def replace(cls):return object\n@replace\nclass Base:\n value:int\n'
              'class Report(Base):\n def __init__(self,value):self.value=value\n'
              'def read(record):\n value = record\n')
    with pytest.raises(InvalidEvidence):
        generate_binding(record_profile(), {'native.py':source}, grammar_version='1.4.0')


def test_unexecuted_nested_body_assignment_does_not_shadow_original_base():
    source = ('class Base:\n value:int\ndef unused():\n Base=object\n return Base\n'
              'class Report(Base):\n def __init__(self,value):self.value=value\n'
              'def read(record):\n value = record\n')
    assert generate_binding(record_profile(), {'native.py':source}, grammar_version='1.4.0')['sites']


def private_record_profile(field):
    p = record_profile()
    p['record_types']['report']['fields'] = [field]
    p['sites']['return']['projection']['flag']['path'][0]['stored'] = field
    return p


@pytest.mark.parametrize('declaration', [
    '__value:int\n def __init__(self,value):\n  self.__value=value\n  self.__dict__["__value"]=999',
    'def __init__(self,value):\n  self.__value:int=value\n  self.__dict__["__value"]=999',
])
def test_private_annotation_does_not_qualify_unmangled_decoy_field(declaration):
    source = 'class Report:\n '+declaration+'\ndef read(record):\n value = record\n'
    with pytest.raises(InvalidEvidence):
        generate_binding(private_record_profile('__value'), {'native.py':source}, grammar_version='1.4.0')


@pytest.mark.parametrize('prefix', ['_', '___'])
def test_native_private_locals_keep_actual_mangled_identity(prefix):
    name = prefix+'Native'
    mangled = '_Native__secret'
    source = f'class {name}:\n def method(self,n):\n  __secret = n\n  return __secret\n'
    _, _, events, scope = observe(source, function=name+'.method', anchor='__secret = n',
                                  projection={'local':mangled})
    assert scope[name]().method(17) == 17
    assert events[0]['values']['flag'] == 17


def test_recursive_zero_argument_super_method_preserves_native_call_order():
    source = ('calls=[]\nclass Base:\n def method(self,n):\n  calls.append(n)\n  return n+1\n'
              'class Native(Base):\n def method(self,n):\n  return super().method(n)\n')
    _, _, events, scope = observe(source, anchor='return super().method(n)',
                                  position='return_value', projection={'return':True}, activation=True)
    assert scope['Native']().method(21) == 22
    assert scope['calls'] == [21]
    assert events[0]['values']['flag'] == 22


def test_finally_override_does_not_relabel_selected_return_as_actual_return():
    source = 'class Native:\n def method(self,n):\n  try:\n   return n\n  finally:\n   return 900\n'
    _, _, events, scope = observe(source, anchor='return n', position='return_value', projection={'return':True})
    assert scope['Native']().method(13) == 900
    assert events[0]['values']['flag'] == 13


def test_async_cancellation_preserves_finally_and_emits_no_unreached_return():
    source = ('import asyncio\nclass Native:\n async def method(self,n,entered):\n'
              '  try:\n   entered.set()\n   await asyncio.sleep(60)\n   return n\n'
              '  finally:\n   n.append("closed")\n')
    _, _, events, scope = observe(source, anchor='return n', position='return_value',
                                  projection={'return':True}, activation=True)
    async def scenario():
        values=[]; entered=asyncio.Event()
        task=asyncio.create_task(scope['Native']().method(values,entered))
        await entered.wait(); task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        return values
    assert asyncio.run(scenario()) == ['closed']
    assert events == []


@pytest.mark.parametrize('definition', [
    'import math as __zr_observe__',
    'from math import pi as __zr_return__',
    'try:\n raise RuntimeError()\nexcept RuntimeError as __zr_activation__:\n pass',
    'match {}:\n case {**__zr_observe__}:\n  pass',
    'def unused(__zr_activation__):pass',
])
def test_all_statically_bound_unmangled_plumbing_names_refused(definition):
    with pytest.raises(InvalidEvidence):
        observe(definition+'\nclass Native:\n def method(self,n):\n  value = n\n')


def test_multiple_inheritance_exact_stored_field_with_no_descriptor_calls():
    source = ('class Left:\n value:int\nclass Right:\n other:int\nclass Report(Left,Right):\n'
              ' def __init__(self,value):self.value=value\n'
              ' def __getattribute__(self,name):raise AssertionError("native lookup called")\n'
              'def read(record):\n value = record\n return value\n')
    profile=record_profile()
    binding=generate_binding(profile, {'native.py':source}, grammar_version='1.4.0')
    module=types.ModuleType('native'); previous=sys.modules.get('native');sys.modules['native']=module
    events=[]
    class Sink:
        def emit(self,event):events.append(event);return True
    try:
        exec(binding['transformed']['native.py'],module.__dict__)
        registry=register_records(profile,binding,{'report':module.Report})
        module.__zr_observe__=recorder(profile,binding,Sink(),101,records=registry)
        obj=module.Report(31)
        assert module.read(obj) is obj
        assert events[0]['values']['flag'] == 31
    finally:
        if previous is None:sys.modules.pop('native',None)
        else:sys.modules['native']=previous


def test_constructor_positional_only_self_annotation_is_real_store():
    source = ('class Report:\n def __init__(this,/,value):\n  this.value:int=value\n'
              'def read(record):\n value = record\n')
    assert generate_binding(record_profile(),{'native.py':source},grammar_version='1.4.0')['sites']


@pytest.mark.parametrize('version', ['1.0.0','1.1.0','1.2.0','1.3.0'])
def test_no_old_grammar_gains_method_admission(version):
    p=one_site('Native.method','value = n','after',{'local':'value'})
    with pytest.raises(InvalidEvidence):
        generate_binding(p,{'native.py':'class Native:\n def method(self,n):\n  value = n\n'},grammar_version=version)
