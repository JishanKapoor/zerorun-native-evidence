"""Exact ten archived logs through unchanged native components, no patch execution."""
import hashlib,importlib,json,sys,time,types
from pathlib import Path
for name,rel in [('swebench','swebench'),('swebench.harness','swebench/harness')]:
    m=types.ModuleType(name);m.__path__=[str(Path('/source')/rel)];sys.modules[name]=m
g=importlib.import_module('swebench.harness.grading');typ=importlib.import_module('swebench.types');parsers=importlib.import_module('swebench.harness.log_parsers.python')
cohort=json.loads(Path('/cohort/protocol/swe-cohort.json').read_text());tasks={t['instance_id']:t for t in cohort['tasks']};records={(r['archive'],r['instance_id']):r for r in cohort['records']}
logs=json.loads(Path('/study/protocol/log-acquisition.json').read_text())['records'];rows=[];count=0;start=time.monotonic()
for log in logs:
    task=tasks[log['instance_id']];pred=records[(log['archive'],log['instance_id'])];path=Path('/study')/log['path'];raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=log['sha256']:raise RuntimeError('Log identity mismatch')
    parser=parsers.MAP_REPO_TO_PARSER_PY[task['repo']];parser_name=parser.__name__
    if parser_name not in g.PARSER_REGISTRY:raise RuntimeError('No native parser identity')
    spec=typ.TestSpec(task['instance_id'],'component-only',[],task['repo'],task['version'],task['FAIL_TO_PASS'],task['PASS_TO_PASS'],parser_name,'pass_and_fail')
    gold={k:task[k] for k in ['FAIL_TO_PASS','PASS_TO_PASS']};count+=1;selected,found=g.get_logs_eval(spec,str(path));count+=1;native_report=g.get_eval_tests_report(selected,gold);count+=1;resolution=g.get_resolution_status(native_report)
    count+=1;full=parser(raw.decode(),spec)
    calls=[]
    def callback(frame,event,arg):
        if event=='return' and frame.f_code is parser.__code__ and type(arg) is dict:calls.append(dict(arg))
    sys.setprofile(callback)
    try:count+=1;observed,observed_found=g.get_logs_eval(spec,str(path))
    finally:sys.setprofile(None)
    count+=1;observed_report=g.get_eval_tests_report(observed,gold);count+=1;observed_resolution=g.get_resolution_status(observed_report)
    obs={'source_sha256':hashlib.sha256(Path(g.__file__).read_bytes()).hexdigest(),'parser_calls':calls,'selected':observed,'found':observed_found,'observer_coverage':bool(calls),'native_report':observed_report,'native_resolution':observed_resolution}
    row={'id':log['archive']+'|'+task['instance_id'],'family':'swe','provenance':{'source_sha256':obs['source_sha256'],'input_sha256':log['sha256'],'candidate_sha256':pred['patch_sha256']},'observation':obs,'native_reference':{'selected':selected,'found':found,'report':native_report,'resolution':resolution},'diagnostics':{'whole_log_parser_map':full,'missing_f2p':[i for i in task['FAIL_TO_PASS'] if i not in selected],'missing_p2p':[i for i in task['PASS_TO_PASS'] if i not in selected],'obligations':gold,'parser':parser_name,'raw_log_bytes':len(raw),'observation_preserved':selected==observed and native_report==observed_report and resolution==observed_resolution,'markers':{'start':g.START_TEST_OUTPUT in raw.decode(),'end':g.END_TEST_OUTPUT in raw.decode()}}}
    rows.append(row);print(json.dumps({'id':row['id'],'native_found':found,'selected_statuses':len(selected),'full_log_statuses':len(full),'resolution':resolution,'preserved':row['diagnostics']['observation_preserved']}),flush=True)
with Path('/results/records.json').open('x') as f:json.dump({'level':'Unchanged native saved-log components; no fresh patch execution','records':rows,'component_entry_calls':count,'wall_seconds':time.monotonic()-start},f,indent=2)
