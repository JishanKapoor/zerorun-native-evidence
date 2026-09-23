import asyncio
import copy

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, recorder
from test_native_projection import one_site


def prepared(source, *, function='outer', anchor='value = n', position='after'):
    p = one_site(function, anchor, position, {'local': 'n'})
    p['sites']['return']['projection']['obligation'] = {'activation': True}
    b = generate_binding(p, {'native.py': source}, grammar_version='1.3.0')
    events = []
    class Sink:
        def emit(self, value):
            events.append(copy.deepcopy(value))
            return type(value) is dict
    callback = recorder(p, b, Sink(), 123)
    scope = {'__zr_observe': callback}
    exec(b['transformed']['native.py'], scope)
    return p, b, events, callback, scope


def test_recursion_and_sequential_reuse_have_distinct_actual_activations():
    source = '''def outer(n):
    """native documentation"""
    value = n
    if n: outer(n-1)
    return value
'''
    _, _, events, _, scope = prepared(source)
    assert scope['outer'].__doc__ == 'native documentation'
    assert scope['outer'](3) == 3
    assert scope['outer'](1) == 1
    assert [row['identity']['obligation'] for row in events] == list(range(1, 7))
    assert [row['values']['flag'] for row in events] == [3, 2, 1, 0, 1, 0]


def test_multiple_sites_in_one_activation_retain_same_identity():
    source = 'def outer(n):\n value = n\n return value\n'
    p = one_site('outer', 'value = n', 'after', {'local': 'n'})
    p['sites']['return']['projection']['obligation'] = {'activation': True}
    p['sites']['second'] = copy.deepcopy(p['sites']['return'])
    p['sites']['second'].update(anchor='return value', position='before_return')
    b = generate_binding(p, {'native.py': source}, grammar_version='1.3.0')
    events = []
    class Sink:
        def emit(self, value): events.append(value); return True
    scope = {'__zr_observe': recorder(p, b, Sink(), 123)}
    exec(b['transformed']['native.py'], scope)
    assert scope['outer'](7) == 7
    assert [e['identity']['obligation'] for e in events] == [1, 1]
    assert b['transformed']['native.py'].count('.enter(') == 1


def test_async_activation_begins_on_execution_and_survives_await():
    source = 'async def outer(n, gate):\n value = n\n await gate.wait()\n return value\n'
    p = one_site('outer', 'value = n', 'after', {'local': 'n'})
    p['sites']['return']['projection']['obligation'] = {'activation': True}
    p['sites']['second'] = copy.deepcopy(p['sites']['return'])
    p['sites']['second'].update(anchor='return value', position='before_return')
    b = generate_binding(p, {'native.py': source}, grammar_version='1.3.0')
    events = []
    class Sink:
        def emit(self, value): events.append(value); return True
    scope = {'__zr_observe': recorder(p, b, Sink(), 123)}
    exec(b['transformed']['native.py'], scope)
    async def run():
        first, second = asyncio.Event(), asyncio.Event()
        coro = scope['outer'](1, first)
        assert events == []
        a = asyncio.create_task(coro)
        z = asyncio.create_task(scope['outer'](2, second))
        await asyncio.sleep(0)
        second.set(); await z
        first.set(); await a
    asyncio.run(run())
    assert [(e['values']['flag'], e['identity']['obligation']) for e in events] == [(1,1),(2,2),(2,2),(1,1)]


def test_cancelled_activation_not_reused_or_reported_completed():
    source = 'async def outer(n, gate):\n await gate.wait()\n value = n\n return value\n'
    _, _, events, _, scope = prepared(source)
    async def run():
        gate = asyncio.Event()
        task = asyncio.create_task(scope['outer'](1, gate)); await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        gate.set()
        assert await scope['outer'](2, gate) == 2
    asyncio.run(run())
    assert [(e['values']['flag'], e['identity']['obligation']) for e in events] == [(2,2)]


@pytest.mark.parametrize('version', ['1.0.0','1.1.0','1.2.0'])
def test_old_binding_grammar_refuses_activation(version):
    p = one_site('outer', 'value = n', 'after', {'local':'n'})
    p['sites']['return']['projection']['obligation'] = {'activation':True}
    with pytest.raises(InvalidEvidence):
        generate_binding(p, {'native.py':'def outer(n):\n value = n\n'}, grammar_version=version)


@pytest.mark.parametrize('collision', ['__zr_activation = 1', 'import math as __zr_activation',
                                      'global __zr_activation', 'def __zr_activation(): pass'])
def test_reserved_activation_cannot_collide_with_native_names(collision):
    source = 'def outer(n):\n '+collision+'\n value = n\n'
    with pytest.raises(InvalidEvidence): prepared(source)


def test_activation_exhaustion_and_unknown_scope_reject_telemetry_only():
    _, _, events, callback, scope = prepared('def outer(n):\n value = n\n return value\n')
    for i in range(32768):
        assert callback.enter('native.py:outer') == i+1
    assert scope['outer'](7) == 7
    assert len(events) == 2 and all(type(e) is object for e in events)
    assert callback.enter('native.py:unknown') is None


def test_native_exception_identity_preserved_after_activation_entry():
    source = 'def outer(n, error):\n value = n\n raise error\n'
    _, _, events, _, scope = prepared(source)
    error = RuntimeError('original')
    with pytest.raises(RuntimeError) as caught: scope['outer'](4, error)
    assert caught.value is error and events[0]['identity']['obligation'] == 1
