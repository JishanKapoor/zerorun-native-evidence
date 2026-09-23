import contextlib

import pytest

from zerorun_harness.binding import generate_binding
from zerorun_harness.lifecycle_binding import generate_lifecycle_binding,validate_lifecycle_binding
from test_native_projection import one_site


def instrument(source):
    p=one_site('outer','marker = 1','after',{'local':'marker'})
    b=generate_binding(p,{'native.py':source})
    e=generate_lifecycle_binding(b,{'native.py':[{'function':'outer','role':'worker'}]})
    validate_lifecycle_binding(b,e)
    return e['transformed']['native.py']


@pytest.mark.parametrize('body,expected,error',[
    ('return value',7,None),
    ('try:\n    return value\nfinally:\n    log.append("cleanup")',7,None),
    ('try:\n    return value\nfinally:\n    return 9',9,None),
    ('raise value',None,ValueError),
    ('try:\n    return 7\nfinally:\n    raise value',None,ValueError),
    ('pass',None,None),
])
def test_exit_after_native_cleanup_preserves_control_flow(body,expected,error):
    log=[]
    value=ValueError('native exception') if error else 7
    source='def outer(value,log):\n    "native doc"\n    marker = 1\n'+''.join('    '+line+'\n' for line in body.splitlines())
    @contextlib.contextmanager
    def lifecycle(role,function,state):
        assert role=='worker' and function=='outer' and state['value'] is value
        log.append('enter')
        try: yield
        except BaseException as exc:
            log.append(('exit-error',type(exc).__name__))
            raise
        else:log.append('exit-normal')
    scope={'__zr_lifecycle':lifecycle,'__zr_observe':lambda *a:None}
    exec(compile(instrument(source),'native.py','exec'),scope)
    assert scope['outer'].__doc__=='native doc'
    if error:
        with pytest.raises(error) as caught:scope['outer'](value,log)
        assert caught.value is value and log[-1]==('exit-error','ValueError')
    else:
        assert scope['outer'](value,log)==expected
        assert log[-1]=='exit-normal'
    assert log[0]=='enter'
    if 'cleanup' in body: assert log==['enter','cleanup','exit-normal']


def test_return_operand_is_evaluated_once_same_object():
    calls=[];value=object()
    @contextlib.contextmanager
    def life(*args):yield
    scope={'__zr_lifecycle':life,'__zr_observe':lambda *a:None}
    exec(instrument('def outer(fn):\n marker = 1\n return fn()\n'),scope)
    def fn():calls.append('called');return value
    assert scope['outer'](fn) is value and calls==['called']
