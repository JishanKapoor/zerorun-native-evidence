"""Reserved activation state must not silently alter admitted native locals."""
import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding
from test_native_projection import one_site


@pytest.mark.parametrize('expression', ["locals()", "vars()", "eval('n')", "exec('value = n')"])
def test_activation_rejects_native_local_namespace_introspection(expression):
    source = f'def outer(n):\n native = {expression}\n value = n\n return native\n'
    p = one_site('outer','value = n','after',{'local':'n'})
    p['sites']['return']['projection']['obligation'] = {'activation':True}
    with pytest.raises(InvalidEvidence,match='introspection'):
        generate_binding(p,{'native.py':source},grammar_version='1.3.0')


def test_nonlocal_object_vars_does_not_inspect_activation_namespace():
    source='def outer(n, obj):\n native = vars(obj)\n value = n\n return native\n'
    p=one_site('outer','value = n','after',{'local':'n'})
    p['sites']['return']['projection']['obligation']={'activation':True}
    assert generate_binding(p,{'native.py':source},grammar_version='1.3.0')['sites']


@pytest.mark.parametrize('body', [
    'import builtins\n native = builtins.locals()\n value = n\n return native',
    'from builtins import locals as capture\n native = capture()\n value = n\n return native',
    'def inner(captured=locals()):\n  return captured\n value = n\n return inner()',
    'class Inner(dict, captured=locals()):\n  pass\n value = n\n return Inner',
    'capture = locals\n second = capture\n native = second()\n value = n\n return native',
])
def test_definition_expressions_and_known_aliases_cannot_capture_new_local(body):
    source = 'def outer(n):\n '+body+'\n'
    p=one_site('outer','value = n','after',{'local':'n'})
    p['sites']['return']['projection']['obligation']={'activation':True}
    with pytest.raises(InvalidEvidence,match='introspection'):
        generate_binding(p,{'native.py':source},grammar_version='1.3.0')
