import asyncio
import ast
import copy
from pathlib import Path
import sys
import pytest

from zerorun_harness.binding import generate_binding,recorder,UnsupportedBinding
from test_native_projection import one_site


SOURCE='''async def outer(scorer, state):
    score = await scorer()
    state['first'] = score
    return score
'''


def bound(source=SOURCE,function='outer',anchor="state['first'] = score"):
    p=one_site(function,anchor,'after',{'local':'score'})
    b=generate_binding(p,{'native.py':source},grammar_version='1.3.0');events=[]
    class Sink:
        def emit(self,e):events.append(copy.deepcopy(e));return True
    scope={'__zr_observe':recorder(p,b,Sink(),123)}
    exec(b['transformed']['native.py'],scope)
    return scope,events,b


def test_async_native_await_and_commit_execute_once():
    scope,events,b=bound();calls=[];state={}
    async def scorer():calls.append(1);await asyncio.sleep(0);return 7
    assert asyncio.run(scope['outer'](scorer,state))==7
    assert state=={'first':7} and calls==[1] and len(events)==1
    assert events[0]['values']['flag']==7 and b['grammar_version']=='1.3.0'


def test_scorer_exception_never_emits_commit_and_preserves_identity():
    scope,events,_=bound();error=ValueError('native');state={}
    async def scorer():raise error
    with pytest.raises(ValueError) as caught:asyncio.run(scope['outer'](scorer,state))
    assert caught.value is error and state=={} and events==[]


def test_cancelled_await_preserves_cancellation_and_has_no_false_commit():
    scope,events,_=bound();state={}
    async def runner():
        entered=asyncio.Event()
        async def scorer():entered.set();await asyncio.Future()
        task=asyncio.create_task(scope['outer'](scorer,state))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(runner())
    assert state=={} and events==[]


def test_later_failure_retains_earlier_native_sibling_commit():
    source=SOURCE.replace('    return score','    await failing()\n    return score').replace('scorer, state','scorer, state, failing')
    scope,events,_=bound(source);state={}
    async def first():return 7
    async def second():raise RuntimeError('later scorer')
    with pytest.raises(RuntimeError):asyncio.run(scope['outer'](first,state,second))
    assert state=={'first':7} and len(events)==1 and events[0]['values']['flag']==7


@pytest.mark.parametrize('version',['1.0.0','1.1.0','1.2.0'])
def test_old_grammars_keep_original_async_refusal(version):
    p=one_site('outer',"state['first'] = score",'after',{'local':'score'})
    with pytest.raises(UnsupportedBinding):generate_binding(p,{'native.py':SOURCE},grammar_version=version)


@pytest.mark.parametrize('source',[
    'async def outer():\n score = 1\n yield score\n',
    '@decorator\nasync def outer():\n score = 1\n return score\n'])
def test_unqualified_generator_and_decorator_are_refused(source):
    with pytest.raises(UnsupportedBinding):bound(source,anchor='score = 1')


def test_conditionally_defined_nested_coroutine_has_lexical_identity():
    source='''async def outer(scorer,state):
    if True:
        async def inner():
            score = await scorer()
            state['first'] = score
            return score
    return await inner()
'''
    scope,events,_=bound(source,function='outer.inner');state={}
    async def scorer():return 7
    assert asyncio.run(scope['outer'](scorer,state))==7 and len(events)==1


def test_actual_pinned_inspect_commit_can_be_structurally_bound_opt_in():
    root=Path(__file__).resolve().parents[1]/'validation'/'inspect_internal'
    sys.path.insert(0,str(root))
    try:
        from feasibility import async_commit_probe
        p,sources=async_commit_probe()
        source=next(iter(sources.values()))
        for line in [3027,3047]:
            node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assign) and n.lineno==line)
            p['sites']['site']['anchor']=ast.unparse(node)
            binding=generate_binding(p,sources,grammar_version='1.3.0')
            assert len(binding['sites'])==1 and binding['sites'][0]['line']==line
    finally:sys.path.remove(str(root))
