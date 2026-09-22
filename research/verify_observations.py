"""Run from public research/; replay all new observations without native execution."""
import hashlib,json,time
from pathlib import Path
from zerorun_harness import audit
R=Path(__file__).resolve().parent
start=time.perf_counter();rows=[]
for p in sorted((R/'observations').glob('*-capture.json')):
    data=json.loads(p.read_text());result=audit(data);expected=json.loads(p.with_name(p.name.replace('-capture','-audit')).read_text())
    if result!=expected:raise RuntimeError('Replay mismatch '+p.name)
    rows.append({'file':p.name,'records':len(result['records']),'counts':result['counts'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
if len(rows)!=4 or sum(r['records'] for r in rows)!=676:raise RuntimeError('Incomplete study inventory')
print(json.dumps({'passed':True,'records':676,'bundles':rows,'elapsed_seconds':time.perf_counter()-start,'candidate_calls':0},indent=2))
