"""Reproduce the native scientific summary without ZeroRun/PyContract imports."""
import collections,json,sys
from pathlib import Path
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R.parent/'ordinary'));from qualification import qualify
profiles=json.loads((R.parent/'src/zerorun_harness/resources/profiles.json').read_text());sources={k:v['source_sha256'] for k,v in profiles.items()}
captures={name:{r['id']:r for r in json.loads((R/'observations'/(name+'-capture.json')).read_text())['records']} for name in ['evalplus-c05b20b2','evalplus-6eb1e199','swe-a5ecda66','swe-489a34eb']}
metrics={};actions=collections.Counter();changes=[]
for rev in ['c05b20b2','6eb1e199']:
    rows=captures['evalplus-'+rev]
    if set(rows)!={'HumanEval/'+str(i)+'|'+bank for i in range(164) for bank in ['base','plus']}:raise RuntimeError('Incomplete native population')
    metrics[rev]={'base_pass':sum(rows['HumanEval/'+str(i)+'|base']['native_reference']['grade']=='pass' for i in range(164)),'plus_pass':sum(rows['HumanEval/'+str(i)+'|plus']['native_reference']['grade']=='pass' for i in range(164)),'joint_pass':sum(all(rows['HumanEval/'+str(i)+'|'+bank]['native_reference']['grade']=='pass' for bank in ['base','plus']) for i in range(164)),'denominator':164}
for i in range(164):
    ident='HumanEval/'+str(i);records=[captures['evalplus-'+rev][ident+'|'+bank] for rev in ['c05b20b2','6eb1e199'] for bank in ['base','plus']]
    q=[qualify(r,sources)['status'] for r in records]
    action='USE_INDEPENDENT_NATIVE_RESULTS_ONLY' if any(s in ['INCONCLUSIVE','UNSUPPORTED'] for s in q) else 'RETAIN_NATIVE_RESULTS_AND_COMMITMENT_CONTRADICTION' if 'VIOLATION' in q else 'CAPTURED_RELATIONSHIP_SUPPORTED'
    actions[action]+=1
    if [r['native_reference']['grade'] for r in records[:2]]!=[r['native_reference']['grade'] for r in records[2:]]:changes.append(ident)
swe=captures['swe-a5ecda66'];other=captures['swe-489a34eb']
if len(swe)!=10 or set(swe)!=set(other):raise RuntimeError('Incomplete SWE population')
for ident,r in swe.items():
    if r['native_reference']['found'] and other[ident]['native_reference']['found']:actions['NATIVE_LOG_COMPARISON_SUPPORTED']+=1
    else:actions['ARCHIVE_INCOMPATIBLE_WITH_REQUIRED_NATIVE_MARKERS']+=1
result={'records':174,'metrics':metrics,'scientific_actions':dict(actions),'native_changes':changes}
expected=json.loads((R/'scientific-summary.json').read_text())
if any(result[k]!=expected[k] for k in result):raise RuntimeError('Scientific summary mismatch')
print(json.dumps({'passed':True,**result,'production_checker_imported':False,'candidate_calls':0},indent=2))
