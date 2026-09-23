"""Physical transport qualification with pre-specified native and wire expectations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

P=Path('/package')
F=Path('/fixtures')
O=Path('/results')
N=Path('/native')
adapter=F/'native_adapter.py';adapter_sha=hashlib.sha256(adapter.read_bytes()).hexdigest()
guard_sha=hashlib.sha256((N/'evalplus/eval/utils.py').read_bytes()).hexdigest()
expected={'native_value':17,'native_marker':'unchanged'}
rows=[]
bootstrap="import sys;sys.path.insert(0,sys.argv.pop(1));"
code=bootstrap+"from zerorun_harness.telemetry import capture_native;import json;from pathlib import Path;r=json.loads(Path(sys.argv[1]).read_text());v=capture_native(**r);Path(sys.argv[2]).write_text(json.dumps(v))"
fault_code=bootstrap+"from zerorun_harness._telemetry_supervisor import acquire;import json;from pathlib import Path;r=json.loads(Path(sys.argv[1]).read_text());v=acquire(r,_collector_fault=sys.argv[3]);Path(sys.argv[2]).write_text(json.dumps(v))"
baseline=subprocess.run([sys.executable,'-I',str(F/'native_guard_reference.py'),str(N),guard_sha],capture_output=True,text=True,timeout=15)
(O/'guard-baseline.stdout.txt').write_text(baseline.stdout)
(O/'guard-baseline.stderr.txt').write_text(baseline.stderr)
assert baseline.returncode==0 and json.loads(baseline.stdout)==expected
cases=[('normal',True,True),('native_guard',True,True),('stdio',True,True),('broken_fd',True,False),
       ('missing_seal',True,False),('partial_frame',True,False),('corrupt_frame',True,False),
       ('bad_callback',True,False),('silent_callback',True,True),('trace_cap',True,False),
       ('native_timeout',False,True),('native_termination',False,True),('native_interrupt',False,True),
       ('deadline',False,False),('timing_boundary',True,True),('collector_stopped',True,False),('collector_broken',True,False)]
for mode,native_ok,transport_ok in cases:
    argument={'mode':mode,'source':str(N),'guard_sha256':guard_sha}
    fault=mode.removeprefix('collector_') if mode.startswith('collector_') else None
    if fault:argument['mode']='flood'
    request=dict(adapter=str(adapter),adapter_sha256=adapter_sha,argument=argument,start_method='fork',
                 wall_seconds=.08 if mode=='deadline' else 10,max_trace_bytes=4096 if mode=='trace_cap' else 16*1024*1024)
    inp=O/(mode+'-request.json');out=O/(mode+'-result.json');inp.write_text(json.dumps(request))
    args=[sys.executable,'-I','-c',fault_code if fault else code,str(P),str(inp),str(out)]
    if fault:args.append(fault)
    proc=subprocess.run(args,capture_output=True,text=True,timeout=30)
    (O/(mode+'.stdout.txt')).write_text(proc.stdout);(O/(mode+'.stderr.txt')).write_text(proc.stderr)
    assert proc.returncode==0, (mode,proc.stderr)
    r=json.loads(out.read_text())
    checks={'native_complete':r['health']['native_complete'] is native_ok,
            'transport_intact':r['health']['transport_intact'] is transport_ok,
            'no_semantic_coverage_inference':r['health']['semantic_coverage'] is None,
            'separate_supervisor_producer':r['supervisor_pid']!=r['producer_pid'],
            'fresh_supervisor':r['supervisor_pid'] not in [x['supervisor_pid'] for x in rows]}
    if native_ok:checks['native_result_preserved']=r['native']['returned']==expected
    if mode=='normal':checks['native_wire_values']= [e['event'] for e in r['transport']['events']]==[{'native_fact':True,'index':0},{'native_fact':True,'index':1}]
    if mode=='native_guard':checks['initialized_before_real_guard']=r['native']['telemetry_initialized_before_adapter'] is True
    if mode=='stdio':checks['stdout_stderr_preserved']=proc.stdout=='NATIVE_STDOUT\n' and proc.stderr=='NATIVE_STDERR\n'
    if mode=='native_timeout':checks['native_exception_preserved']=r['native']['exception']=='TimeoutError' and r['worker_exitcode']==1
    if mode=='native_termination':checks['native_exception_preserved']=r['native']['exception']=='SystemExit' and r['worker_exitcode']==7
    if mode=='native_interrupt':checks['native_exception_preserved']=r['native']['exception']=='KeyboardInterrupt' and r['worker_exitcode']==1
    if mode=='deadline':checks['deadline_termination']=r['outer_timeout'] and r['worker_exitcode']<0
    row=dict(case=mode,passed=all(checks.values()),checks=checks,supervisor_pid=r['supervisor_pid'],
             result_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),worker_exitcode=r['worker_exitcode'])
    rows.append(row);print(json.dumps(row),flush=True)
    with (O/'progress.json').open('w') as f:json.dump(rows,f,indent=2)
    assert row['passed'],(mode,checks,r)
summary=dict(passed=True,cases=len(rows),checks=sum(len(r['checks']) for r in rows),rows=rows,
             adapter_sha256=adapter_sha,guard_sha256=guard_sha,guard_component_calls=2,
             authored_adapter_calls=len(rows),primary_candidate_bank_calls=0,canonical_reference_calls=0,
             pid=os.getpid(),uid=os.getuid(),python=sys.version)
with (O/'summary.json').open('x') as f:json.dump(summary,f,indent=2)
