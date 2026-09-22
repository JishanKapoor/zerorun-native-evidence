"""Native trusted reference/calibration, isolated and separately counted."""
import datetime,hashlib,json,multiprocessing as mp,os,pickle,sys,time
from pathlib import Path
sys.path.insert(0,'/source');os.environ['HUMANEVAL_OVERRIDE_PATH']='/cohort/data/HumanEvalPlus-v019.jsonl.gz'
from evalplus.data import get_human_eval_plus
from evalplus.gen.util import trusted_exec
from evalplus.eval.utils import time_limit
if sys.flags.optimize!=0:raise RuntimeError('Optimized mode unsupported')
tasks=get_human_eval_plus();out=Path('/results');start=time.monotonic();calls=0;rows=[]
for number in range(164):
    ident='HumanEval/'+str(number);task=tasks[ident];record={'task_id':ident,'banks':{}}
    for bank in ['base','plus']:
        t=time.monotonic();calls+=1
        try:
            with time_limit(120):values,times=trusted_exec(task['prompt']+task['canonical_solution'],task[bank+'_input'],task['entry_point'],record_time=True)
            record['banks'][bank]={'outputs':values,'times':times,'error':None}
        except BaseException as exc:record['banks'][bank]={'error':type(exc).__name__+': '+str(exc)}
        print(json.dumps({'task_id':ident,'bank':bank,'inputs':len(task[bank+'_input']),'error':record['banks'][bank]['error'],'elapsed_seconds':time.monotonic()-t,'canonical_calls':calls}),flush=True)
    data=pickle.dumps(record,protocol=4);name='reference-'+str(number)+'.pkl'
    with (out/name).open('xb') as f:f.write(data)
    rows.append({'task_id':ident,'file':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
with (out/'manifest.json').open('x') as f:json.dump({'classification':'Native canonical code outputs and calibration; not candidate results','rows':rows,'canonical_bank_calls':calls,'wall_seconds':time.monotonic()-start,'native_trusted_exec_sha256':hashlib.sha256(Path('/source/evalplus/gen/util/__init__.py').read_bytes()).hexdigest(),'data_sha256':hashlib.sha256(Path(os.environ['HUMANEVAL_OVERRIDE_PATH']).read_bytes()).hexdigest()},f,indent=2)
