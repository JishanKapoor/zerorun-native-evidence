"""Independent preservation/refusal controls for opt-in coroutine binding."""

import asyncio
import copy

import pytest

from zerorun_harness.binding import generate_binding, recorder, UnsupportedBinding
from test_native_projection import one_site


def paired(source, anchor, *, function="outer", position="after", projection=None):
    profile = one_site(function, anchor, position, projection or {"local": "score"})
    binding = generate_binding(profile, {"native.py": source}, grammar_version="1.3.0")
    events = []

    class Sink:
        def emit(self, event):
            events.append(copy.deepcopy(event))
            return True

    original = {}
    transformed = {"__zr_observe": recorder(profile, binding, Sink(), 123)}
    exec(source, original)
    exec(binding["transformed"]["native.py"], transformed)
    return original["outer"], transformed["outer"], events


def test_cancellation_after_retained_commit_preserves_finally_and_prior_fact():
    source = '''async def outer(state, entered):
    try:
        score = 7
        state.append(score)
        entered.set()
        await never()
    finally:
        state.append('cleanup')
'''.replace("await never()", "await __import__('asyncio').Future()")
    original, observed, events = paired(source, "state.append(score)")

    async def run(function):
        state = []
        entered = asyncio.Event()
        task = asyncio.create_task(function(state, entered))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return state

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == [7, "cleanup"]
    assert [event["values"]["flag"] for event in events] == [7]


def test_cancelled_await_assignment_emits_no_commit_even_if_finally_returns():
    source = '''async def outer(scorer, state):
    try:
        score = await scorer()
        state.append(score)
    finally:
        state.append('cleanup')
        return 99
'''
    original, observed, events = paired(source, "score = await scorer()")

    async def run(function):
        state = []
        entered = asyncio.Event()

        async def scorer():
            entered.set()
            await asyncio.Future()

        task = asyncio.create_task(function(scorer, state))
        await entered.wait()
        task.cancel()
        return await task, state

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == (99, ["cleanup"])
    assert events == []


def test_awaited_return_operand_captured_once_before_finally_override():
    source = '''async def outer(scorer, state):
    try:
        return await scorer()
    finally:
        state.append('cleanup')
        return 99
'''
    original, observed, events = paired(
        source, "return await scorer()", position="return_value", projection={"return": True}
    )

    async def run(function):
        state, calls = [], []

        async def scorer():
            calls.append("native")
            await asyncio.sleep(0)
            return 7

        return await function(scorer, state), state, calls

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == (99, ["cleanup"], ["native"])
    assert [event["values"]["flag"] for event in events] == [7]


def test_awaited_return_cancellation_has_no_operand_fact_and_runs_async_cleanup():
    source = '''async def outer(scorer, state):
    try:
        return await scorer()
    finally:
        await __import__('asyncio').sleep(0)
        state.append('cleanup')
'''
    original, observed, events = paired(
        source, "return await scorer()", position="return_value", projection={"return": True}
    )

    async def run(function):
        entered = asyncio.Event()
        state = []

        async def scorer():
            entered.set()
            await asyncio.Future()

        task = asyncio.create_task(function(scorer, state))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return state

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == ["cleanup"]
    assert events == []


def test_await_exception_identity_and_async_finally_order_preserved():
    source = '''async def outer(scorer, state):
    try:
        score = await scorer()
    finally:
        await __import__('asyncio').sleep(0)
        state.append('cleanup')
'''
    original, observed, events = paired(source, "score = await scorer()")
    error = LookupError("original exception")

    async def run(function):
        state = []

        async def scorer():
            raise error

        with pytest.raises(LookupError) as caught:
            await function(scorer, state)
        assert caught.value is error
        return state

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == ["cleanup"]
    assert events == []


def test_concurrent_invocations_keep_each_local_operand():
    source = '''async def outer(score, gate, state):
    await gate.wait()
    state.append(score)
    return score
'''
    original, observed, events = paired(source, "state.append(score)")

    async def run(function):
        gate = asyncio.Event()
        state = []
        tasks = [asyncio.create_task(function(i, gate, state)) for i in range(12)]
        await asyncio.sleep(0)
        gate.set()
        return await asyncio.gather(*tasks), state

    expected = (list(range(12)), list(range(12)))
    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == expected
    assert [event["values"]["flag"] for event in events] == list(range(12))
    assert len({event["id"] for event in events}) == 12


def test_async_context_exit_failure_preserves_written_fact():
    source = '''async def outer(context, state):
    async with context:
        score = 7
        state.append(score)
    return score
'''
    original, observed, events = paired(source, "state.append(score)")
    error = RuntimeError("native exit")

    async def run(function):
        state = []

        class Context:
            async def __aenter__(self):
                state.append("enter")

            async def __aexit__(self, *args):
                state.append("exit")
                raise error

        with pytest.raises(RuntimeError) as caught:
            await function(Context(), state)
        assert caught.value is error
        return state

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == ["enter", 7, "exit"]
    assert [event["values"]["flag"] for event in events] == [7]


def test_async_iteration_observes_only_executed_native_statements():
    source = '''async def outer(values, state):
    async for score in values:
        if score == 1: continue
        state.append(score)
        if score == 2: break
    return state
'''
    original, observed, events = paired(source, "state.append(score)")

    async def run(function):
        async def values():
            for value in range(4):
                await asyncio.sleep(0)
                yield value
        return await function(values(), [])

    assert asyncio.run(run(original)) == asyncio.run(run(observed)) == [0, 2]
    assert [event["values"]["flag"] for event in events] == [0, 2]


def test_unselected_nested_generator_never_changes_outer_site_multiplicity():
    source = '''async def outer(state):
    async def inner():
        score = 99
        state.append(score)
        yield score
    score = 7
    state.append(score)
    return score
'''
    original, observed, events = paired(source, "state.append(score)")
    assert asyncio.run(original([])) == asyncio.run(observed([])) == 7
    assert [event["values"]["flag"] for event in events] == [7]


def test_ambiguous_conditional_coroutine_definition_refused():
    source = '''async def outer(state):
    if state:
        async def inner():
            score = 7
            state.append(score)
    else:
        async def inner():
            score = 8
            state.append(score)
    return await inner()
'''
    with pytest.raises(UnsupportedBinding, match="ambiguous"):
        paired(source, "state.append(score)", function="outer.inner")


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "1.2.0"])
def test_async_opt_in_does_not_relax_archived_grammar(version):
    source = "async def outer():\n score = 7\n return score\n"
    profile = one_site("outer", "score = 7", "after", {"local": "score"})
    with pytest.raises(UnsupportedBinding):
        generate_binding(profile, {"native.py": source}, grammar_version=version)
