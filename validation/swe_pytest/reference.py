"""Independent native pytest source trace, then original SWE trace in one run."""
import ast
import dis
import json
from pathlib import Path
import sys
from types import CodeType

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from swe_pytest.driver import execute_pytest,write_json,stable_swe
from pytest_native.native import load_native as load_pytest
from swe_joined.native_driver import load_native as load_swe
from swe_joined import reference as swe_reference

PY_POINTS={
 'report-produced':('_pytest/runner.py','call_and_report','report: TestReport = ihook.pytest_runtest_makereport(item=item, call=call)','after'),
 'report-hook-input':('_pytest/runner.py','call_and_report','ihook.pytest_runtest_logreport(report=report)','before'),
 'terminal-decision':('_pytest/terminal.py','TerminalReporter.pytest_runtest_logreport','category, letter, word = res.category, res.letter, res.word','after'),
 'terminal-stats-input':('_pytest/terminal.py','TerminalReporter.pytest_runtest_logreport','self._add_stats(category, [rep])','before'),
 'terminal-stats-commit':('_pytest/terminal.py','TerminalReporter.pytest_runtest_logreport','self._add_stats(category, [rep])','after')}


def points(source,function,anchor):
    tree=ast.parse(source);scope=tree;code=compile(source,'<native>','exec')
    for part in function.split('.'):
        scope,=[n for n in scope.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==part]
        code,=[c for c in code.co_consts if type(c) is CodeType and c.co_name==part]
    wanted=ast.dump(ast.parse(anchor).body[0],include_attributes=False)
    node,=[n for n in ast.walk(scope) if isinstance(n,ast.stmt) and ast.dump(n,include_attributes=False)==wanted]
    instructions=[i for i in dis.get_instructions(code) if i.positions.lineno is not None
        and (node.lineno,node.col_offset)<=(i.positions.lineno,i.positions.col_offset)
        and (i.positions.end_lineno,i.positions.end_col_offset)<=(node.end_lineno,node.end_col_offset)
        and i.opname not in ('NOP','CACHE','RESUME','RETURN_GENERATOR')]
    return node.lineno,node.end_lineno,min(i.offset for i in instructions)


def selected(rows,path,function,point,position):
    start,end,offset=point;rows=[r for r in rows if r['path']==path and r['function']==function];used=set()
    for i,row in enumerate(rows):
        if row['event']!='line' or row['line']!=start or row['offset']!=offset:continue
        if position=='before':yield row
        else:
            following=next(((j,r) for j,r in enumerate(rows[i+1:],i+1) if r['call']==row['call']
                and (r['event']!='line' or not start<=r['line']<=end)),None)
            if following and following[0] not in used and following[1]['event'] in ('line','return'):
                used.add(following[0]);yield following[1]


def trace_pytest(native,case,run,work,output):
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter
    root=Path(sys.modules['_pytest'].__file__).parent
    files={str(root/'runner.py'):'_pytest/runner.py',str(root/'terminal.py'):'_pytest/terminal.py'}
    names={p[1] for p in PY_POINTS.values()};rows=[];calls={}
    def report(value):
        if type(value) is not TestReport:raise ValueError('Reference expected actual exact TestReport')
        data=object.__getattribute__(value,'__dict__')
        return {k:data[k] for k in ['nodeid','when','outcome']}
    def trace(frame,event,arg):
        if frame.f_code.co_filename not in files or frame.f_code.co_qualname not in names:return trace
        if frame not in calls:calls[frame]=len(calls)+1
        if event not in ('line','call','return','exception'):return trace
        state={}
        for name in ['when','category','letter','word']:
            value=frame.f_locals.get(name)
            if type(value) is str:state[name]=value
        for name in ['report','rep']:
            if name in frame.f_locals:state[name]=report(frame.f_locals[name])
        if 'self' in frame.f_locals and 'category' in state:
            owner=frame.f_locals['self']
            if type(owner) is not TerminalReporter:raise ValueError('Reference expected exact TerminalReporter')
            stats=object.__getattribute__(owner,'__dict__')['stats']
            if state['category'] in stats and stats[state['category']]:
                state['stored_report']=report(stats[state['category']][-1])
        rows.append(dict(call=calls[frame],path=files[frame.f_code.co_filename],function=frame.f_code.co_qualname,
                         event=event,line=frame.f_lineno,offset=frame.f_lasti,locals=state))
        return trace
    if sys.gettrace() is not None:raise ValueError('Unexpected existing reference tracer')
    sys.settrace(trace)
    try:result,case_material=execute_pytest(native,case,run,work,output)
    finally:sys.settrace(None)
    return result,case_material,rows,{path:(root/Path(path).name).read_text(encoding='utf-8') for path in set(files.values())}


def py_facts(site,row,run,attempt):
    state=row['locals'];original=state['report'] if site.startswith('report-') else state['rep']
    identity=dict(run=run,candidate='authored-pytest',phase=state['when'] if site.startswith('report-') else original['when'],
                  attempt=attempt,obligation=original['nodeid'])
    native=state['stored_report'] if site=='terminal-stats-commit' else original
    values=dict(nodeid=native['nodeid'],phase_value=state['when'] if site=='report-produced' else native['when'],outcome=native['outcome'])
    if site in ['terminal-decision','terminal-stats-input']:values.update({k:state[k] for k in ['category','letter','word']})
    return dict(identity=identity,values=values)


def main(options):
    fixtures=Path(options['fixture_root']);case=options['case'];output=Path(options['route_output']);output.mkdir()
    pytest,_=load_pytest(json.loads((fixtures/'pytest-source.json').read_text()))
    native=load_swe(options['native_root'],json.loads((fixtures/case['version']/'swe-source.json').read_text()))
    if case.get('no_call'):
        result=dict(pytest=None,swe=None,stable_swe=None);py_rows=[];swe_rows=[];pyfacts={s:[] for s in PY_POINTS};swefacts={s:[] for s in swe_reference.site_points(case['version'])}
    else:
        pytest_result,swe_case,py_rows,sources=trace_pytest(pytest,case,options['run'],options['work']+'/pytest',output)
        swe_result,swe_rows=swe_reference.trace_run(options['native_root'],native,swe_case,options['run'],options['work']+'/swe',output/'swe-calls.jsonl')
        result=dict(pytest=pytest_result,swe=swe_result,stable_swe=stable_swe(swe_result))
        write_json(output/'native-raw.json',dict(native=result,pytest_traces=py_rows,swe_traces=swe_rows))
        pyfacts={site:[py_facts(site,row,options['run'],case['attempt']) for row in selected(py_rows,path,function,points(sources[path],function,anchor),position)]
                 for site,(path,function,anchor,position) in PY_POINTS.items()}
        swefacts={site:[swe_reference.fact(site,row,options['run'],case['version']) for row in swe_reference.point_rows(swe_rows,path,function,
                    swe_reference.source_points(options['native_root'],path,function,expression),position)]
                  for site,(path,function,expression,position) in swe_reference.site_points(case['version']).items()}
    if any(n=='zerorun_harness' or n.startswith('zerorun_harness.') for n in sys.modules):raise ValueError('Reference imported framework')
    return dict(native=result,pytest_facts=pyfacts,swe_facts=swefacts,pytest_traces=py_rows,swe_traces=swe_rows,framework_semantics_imported=False)


if __name__=='__main__':write_json(Path(sys.argv[2]),main(json.loads(Path(sys.argv[1]).read_text())))
