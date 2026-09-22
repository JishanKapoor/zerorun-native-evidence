"""Full fixed population at one exposed version, native and observed separately."""
import hashlib,json,multiprocessing as mp,os,pickle,sys,time
from pathlib import Path
mp.set_start_method('fork')
if sys.flags.optimize!=0:raise RuntimeError('Optimized mode unsupported')
sys.path.insert(0,'/source');import evalplus.eval as native
from application_observer import observe
import gzip
tasks={r['task_id']:r for r in map(json.loads,gzip.decompress(Path('/cohort/data/HumanEvalPlus-v019.jsonl.gz').read_bytes()).splitlines())}
cohort=json.loads(Path('/cohort/protocol/evalplus-cohort.json').read_text());refs=json.loads(Path('/references/manifest.json').read_text());references={r['task_id']:r for r in refs['rows']}
start=time.monotonic();calls=0;counts={'records':0,'reference_errors':0,'native_errors':0};target=Path('/results/records.jsonl')
with target.open('x') as output:
    for item in cohort['records']:
        ident=item['task_id'];task=tasks[ident];r=references[ident];data=(Path('/references')/r['file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=r['sha256']:raise RuntimeError('Reference identity mismatch')
        reference=pickle.loads(data) # trusted local canonical output, verified against the sealed run manifest
        code=(Path('/cohort')/item['path']).read_text()
        if hashlib.sha256(code.encode()).hexdigest()!=item['sha256']:raise RuntimeError('Candidate identity mismatch')
        for bank in ['base','plus']:
            record={'task_id':ident,'bank':bank,'candidate_sha256':item['sha256'],'source_sha256':hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),'reference_sha256':r['sha256'],'input_count':len(task[bank+'_input']),'reference_error':reference['banks'][bank]['error']}
            if record['reference_error'] is not None:counts['reference_errors']+=1
            else:
                ref=reference['banks'][bank];t=time.monotonic();calls+=1
                try:
                    grade,details=native.untrusted_check('humaneval',code,task[bank+'_input'],task['entry_point'],ref['outputs'],task['atol'],ref['times'],fast_check=False,min_time_limit=.1,gt_time_limit_factor=2.)
                    record['independent_native_parent']={'grade':grade,'details':[bool(v) for v in details],'wall_seconds':time.monotonic()-t}
                except BaseException as exc:record['native_error']=type(exc).__name__+': '+str(exc);counts['native_errors']+=1
                calls+=1
                case=dict(dataset='humaneval',entry_point=task['entry_point'],code=code,inputs=task[bank+'_input'],expected=ref['outputs'],time_limits=[max(.1,2*t) for t in ref['times']],atol=task['atol'],fast_check=False)
                record['observation']=observe(native,case)
            counts['records']+=1;output.write(json.dumps(record,separators=(',',':'))+'\n');output.flush()
            print(json.dumps({'task_id':ident,'bank':bank,'calls':calls,'recorded':counts['records'],'elapsed_seconds':time.monotonic()-start,'native_grade':record.get('independent_native_parent',{}).get('grade'),'observer_health':record.get('observation',{}).get('health')}),flush=True)
with Path('/results/summary.json').open('x') as f:json.dump({'counts':counts,'candidate_bank_calls':calls,'wall_seconds':time.monotonic()-start,'source_sha256':hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),'reference_manifest_sha256':hashlib.sha256(Path('/references/manifest.json').read_bytes()).hexdigest(),'peak_memory_bytes':int(Path('/sys/fs/cgroup/memory.peak').read_text())},f,indent=2)
