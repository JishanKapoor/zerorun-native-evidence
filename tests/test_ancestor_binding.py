import pytest
import copy

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, UnsupportedBinding
from test_native_projection import one_site, run_binding


SOURCE = '''def outer(rewrite_reports):
    x = 0
    if rewrite_reports:
        x = 1
    else:
        x = 1
    return x
'''


def declared(branch='body'):
    p = one_site('outer', 'x = 1', 'after', {'local':'x'})
    p['sites']['return']['within'] = [{'header':'if rewrite_reports: pass','branch':branch}]
    return p


@pytest.mark.parametrize('branch,flag', [('body', True),('orelse',False)])
def test_identical_statements_qualified_by_native_branch(branch,flag):
    p=declared(branch)
    b,events,result=run_binding(p,SOURCE,[flag])
    assert result==1 and len(events)==1 and len(b['sites'])==1
    assert run_binding(p,SOURCE,[not flag])[1]==[]


def test_unrelated_condition_cannot_qualify():
    p=declared()
    p['sites']['return']['within'][0]['header']='if unrelated: pass'
    with pytest.raises(UnsupportedBinding,match='multiplicity'):
        generate_binding(p,{'native.py':SOURCE})


@pytest.mark.parametrize('version',['1.0.0','1.1.0'])
def test_ancestor_selection_cannot_relabel_old_grammar(version):
    with pytest.raises(InvalidEvidence,match='Old grammar'):
        generate_binding(declared(),{'native.py':SOURCE},grammar_version=version)


def test_input_loop_and_handler_ancestry_selects_only_actual_loop():
    source='''def outer(items):
    for i, item in enumerate(items):
        try:
            assert item
        except AssertionError:
            x = 1
    x = 1
    return x
'''
    p=one_site('outer','x = 1','after',{'local':'x'})
    p['sites']['return']['within']=[
        {'header':'for i, item in enumerate(items): pass','branch':'body'},
        {'header':'try: pass\nexcept AssertionError: pass','branch':'handler:0'},
    ]
    assert len(run_binding(p,source,[[False]])[1])==1
    assert run_binding(p,source,[[True]])[1]==[]


@pytest.mark.parametrize('header,branch',[
    ('if x: pass','finalbody'),('with x: pass','orelse'),
    ('try: pass\nexcept ValueError: pass','handler:1'),('x = 1','body'),
    ('if x: pass\nif y: pass','body'),('not python code','body'),
])
def test_invalid_ancestry_refused(header,branch):
    p=declared()
    p['sites']['return']['within']=[{'header':header,'branch':branch}]
    with pytest.raises(InvalidEvidence):generate_binding(p,{'native.py':SOURCE})


def test_colocated_views_are_deterministic_and_execute_native_once():
    p=one_site('outer','x = fn()','after',{'local':'x'})
    p['sites']['another']=copy.deepcopy(p['sites']['return'])
    source='def outer(fn):\n x = fn()\n return x\n'
    count=[]
    def fn():count.append(1);return 7
    b,events,result=run_binding(p,source,[fn])
    assert result==7 and count==[1]
    assert [e['site'] for e in events]==['another','return']
    p['sites']=dict(reversed(list(p['sites'].items())))
    assert generate_binding(p,{'native.py':source})==b
    for version in ['1.0.0','1.1.0']:
        with pytest.raises(UnsupportedBinding,match='Multiple declarations'):
            generate_binding(p,{'native.py':source},grammar_version=version)
