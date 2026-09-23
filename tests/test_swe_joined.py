"""Same-execution native chain: source admission, identities and raw references."""
import ast
import copy
from pathlib import Path
import sys

import pytest

from zerorun_harness.binding import generate_binding, validate_binding
from zerorun_harness.declarative import evaluate
from zerorun_harness.api import digest

VALIDATION = Path(__file__).resolve().parents[1] / 'validation'
sys.path.insert(0, str(VALIDATION))
from swe_joined import declarations as decl, reference, ordinary


def sources(version):
    root = VALIDATION / 'swe_joined/source_fixtures' / version
    return {path: (root / name).read_bytes().decode() for path, name in [
        (decl.GRADING, 'grading.py.txt'), (decl.PARSER, 'parser.py.txt'),
        (decl.WRITER, 'run_evaluation.py.txt'), (decl.REPORTING, 'reporting.py.txt')]}


@pytest.mark.parametrize('version,logical,static,kinds', [('before',57,60,30),('after',59,62,32)])
def test_one_binding_spans_all_four_original_modules(version, logical, static, kinds):
    p = decl.profile(version)
    binding = generate_binding(p, sources(version))
    validate_binding(p, binding)
    assert len(p['sites']) == logical and len(binding['sites']) == static
    assert len(p['facts']) == kinds
    assert {s['path'] for s in binding['sites']} == set(decl.SOURCES)
    assert all(s['line'] < 190 for s in binding['sites'] if s['path'] == decl.WRITER)
    assert set(reference.site_points(version)) == set(p['sites'])


def test_bridge_identities_match_by_prospective_source_declaration():
    p = decl.profile('after')
    for left, right in [('report-return','writer-input'),('grading-consumed','tests-embedded'),
                        ('resolution-full','resolution-embedded')]:
        a,b = [p['sites'][k]['projection'] for k in [left,right]]
        assert all(a[k] == b[k] for k in ['run','candidate','phase','attempt','obligation'])
        assert a['instance'] == {'context':'instance'}
        assert b['instance'] == {'local':'instance_id'}
    assert p['sites']['resolution-full']['projection']['phase'] != p['sites']['derivation-reader']['projection']['phase']


def test_all_authored_inputs_are_single_instance_and_all_native_operands_declared():
    for case in decl.case_definitions():
        inv = decl.case_inventory(case, 'run')
        if case['id'] == 'no-native-call':
            assert case['instances'] == inv == []
            continue
        item, = case['instances']
        assert item['id'] == 'a'
        assert {r['obligation'] for r in inv if r['phase'] == 'native-resolution'} == {'FAIL_TO_PASS','PASS_TO_PASS'}
        assert {r['obligation'] for r in inv if r['phase'] == 'resolution'} == {'completed','decision'}
        for bank in ['f2p','p2p']:
            expected = item['fail_to_pass' if bank=='f2p' else 'pass_to_pass']
            assert {r['obligation'] for r in inv if r['phase']=='native-'+bank} == set(expected)


@pytest.mark.parametrize('value,expected', [('RESOLVED_FULL',True),('RESOLVED_PARTIAL',False),('RESOLVED_NO',False)])
def test_actual_native_resolution_enum_requires_matching_report_boolean(value, expected):
    p = decl.profile('after')
    rule = next(r for r in p['rules'] if r['id']=='native-resolution-report-preserved')
    p['rules'] = [rule]
    b = generate_binding(p, sources('after'))
    ident = dict(run='r',candidate=decl.CANDIDATE,instance='a',phase='native-resolution',obligation='PASS_TO_PASS',attempt=1)
    def event(id,kind,site,values):
        return dict(id=id,kind=kind,site=site,identity=ident.copy(),values=values,producer=42,seq=int(id),source_sha256=digest(b["original_sources"]),binding_sha256=b['sha256'])
    # Framework event shape mirrors the actual emitter format, not its verdict.
    events=[event('1','resolution','resolution-'+value.removeprefix('RESOLVED_').lower(),dict(raw=value,role='resolution',f2p=1.0,p2p=1.0)),
            event('2','resolution-embedded','resolution-embedded',dict(raw=expected,role='reported-resolution'))]
    material=dict(id='x',version='1',inventory=[ident],source_sha256=digest(b['original_sources']),input_sha256='b'*64)
    health=dict(binding_sha256=b['sha256'],sites={s:True for s in p['sites']},transport={'42':True},native_complete={rule['id']:True},qualification_sha256='a'*64)
    result=evaluate(p,material,events,health,b['sha256'])
    assert result['records'][0]['status']=='CONFORMS'
    wrong=copy.deepcopy(events);wrong[1]['values']['raw']=not expected
    assert evaluate(p,material,wrong,health,b['sha256'])['records'][0]['status']=='VIOLATION'


def test_reference_has_no_production_policy_or_checker_imports():
    for filename in ['reference.py','internal_reference.py','ordinary.py','native_driver.py']:
        tree=ast.parse((VALIDATION/'swe_joined'/filename).read_text())
        names=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        assert not any(n and ('zerorun' in n or 'declarations' in n) for n in names)


def test_multiline_native_grading_assignment_is_not_double_counted():
    rows=[dict(path='p',function='f',call=1,line=line,event='line',locals={}) for line in [174,175,176,177,178,174,181]]
    assert list(reference.point_rows(rows,'p','f',{174:179},'after'))==[rows[-1]]


def test_independent_raw_bridge_reads_actual_stored_tests_and_resolution():
    row=dict(locals={'instance_id':'a','report_map':{'a':{'tests_status':{'FAIL_TO_PASS':{'success':['t']}},'resolved':False}}})
    tests=reference.fact('tests-embedded',row,'r','after')
    resolution=reference.fact('resolution-embedded',row,'r','after')
    assert tests['values']['raw']=='{"FAIL_TO_PASS":{"success":["t"]}}'
    assert resolution['values']['raw'] is False
    assert tests['identity']['instance']==resolution['identity']['instance']=='a'


@pytest.mark.parametrize('bank,key', [('f2p','FAIL_TO_PASS'),('p2p','PASS_TO_PASS')])
@pytest.mark.parametrize('outcome', ['success','failure'])
def test_list_bridge_reference_preserves_input_and_actual_stored_field_separately(bank,key,outcome):
    row=dict(locals={bank+'_'+outcome:['native-test'], 'results':{key:{outcome:['different-test']}}})
    a=reference.fact('list-'+bank+'-'+outcome+'-input',row,'r','after')
    b=reference.fact('list-'+bank+'-'+outcome+'-stored',row,'r','after')
    assert a['identity']==b['identity']
    assert a['values']['raw']=='["native-test"]'
    assert b['values']['raw']=='["different-test"]'


def test_ordinary_writer_with_header_entry_and_exit_are_one_native_invocation():
    report={'a':{'resolved':False}}
    def header():
        return dict(function='run_instance',event='line',line=181,call=2,locals={'report':copy.deepcopy(report)})
    rows=[dict(function='get_eval_report',event='return',line=301,call=1,
               locals={'instance_id':'a'},returned=copy.deepcopy(report)),header(),header()]
    native=dict(operations=[],artifacts={})
    result=ordinary.check(dict(native=native,traces=rows))
    assert result['internal_checks']==[dict(name='grader-return-to-native-writer-input',passed=True)]
    rows[-1]['locals']['report']['a']['resolved']=True
    assert ordinary.check(dict(native=native,traces=rows))['internal_checks'][0]['passed'] is False


def test_real_cpython_with_statement_emits_both_header_visits(tmp_path):
    scope={}
    source='def writer(path):\n report = {"a": False}\n with path.open("w") as stream:\n  stream.write("native control")\n return report\n'
    exec(compile(source,'with_header_control.py','exec'),scope)
    visits=[]
    def trace(frame,event,arg):
        if frame.f_code.co_filename=='with_header_control.py' and event=='line' and frame.f_lineno==3:
            visits.append(copy.deepcopy(frame.f_locals['report']))
        return trace
    old=sys.gettrace()
    try:
        sys.settrace(trace)
        assert scope['writer'](tmp_path/'value.txt')=={'a':False}
    finally:
        sys.settrace(old)
    assert visits==[{'a':False},{'a':False}]
