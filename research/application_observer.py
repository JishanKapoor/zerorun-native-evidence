"""Fixed-source worker observation for S2, not arbitrary-source adaptation."""
import hashlib,json,multiprocessing as mp,os,select,sys,time
from pathlib import Path
def child(native,case,stat,progress,details,fd):
    os.set_blocking(fd,False);lines=Path(native.__file__).read_text().splitlines();fn=native.unsafe_execute.__code__
    sites={i+1:line.strip() for i,line in enumerate(lines) if ('assert abs(_poly' in line or line.strip() in ['details[i] = True','details[i] = False'])}
    attempted=emitted=dropped=0;pending=None;accepted=set()
    def emit(kind,index):
        nonlocal attempted,emitted,dropped
        attempted+=1;data=(json.dumps({'seq':attempted,'kind':kind,'index':index,'optimize':sys.flags.optimize},separators=(',',':'))+'\n').encode()
        try:
            n=os.write(fd,data)
            if n==len(data):emitted+=1
            else:dropped+=1
        except OSError:dropped+=1
    def trace(frame,event,arg):
        nonlocal pending
        if frame.f_code is not fn:return None
        index=frame.f_locals.get('i')
        if event=='exception':pending=None
        if event=='line':
            if pending is not None:accepted.add(pending);emit('accept',pending);pending=None
            line=sites.get(frame.f_lineno)
            if line and 'assert abs(_poly' in line:pending=index
            elif line=='details[i] = True' and index not in accepted:accepted.add(index);emit('accept',index)
            elif line=='details[i] = False':emit('reject',index)
        return trace
    sys.settrace(trace)
    try:native.unsafe_execute(**case,stat=stat,progress=progress,details=details)
    finally:
        sys.settrace(None)
        try:os.write(fd,(json.dumps({'seal':True,'attempted':attempted,'emitted':emitted,'dropped':dropped})+'\n').encode())
        except OSError:pass
        os.close(fd)
def observe(native,case):
    ctx=mp.get_context('fork');stat=ctx.Value('i',native._UNKNOWN);progress=ctx.Value('i',0);details=ctx.Array('b',[False]*len(case['inputs']))
    rd,wr=os.pipe();os.set_blocking(rd,False);start=time.monotonic();worker=ctx.Process(target=child,args=(native,case,stat,progress,details,wr));worker.start();os.close(wr)
    chunks=[];size=0;limit=False;timeout_seconds=min(60,sum(case['time_limits']))+3
    while time.monotonic()-start<timeout_seconds:
        ready,_,_=select.select([rd],[],[],.03)
        if ready:
            chunk=os.read(rd,65536)
            if not chunk:break
            size+=len(chunk)
            if size>16*1024*1024:limit=True;break
            chunks.append(chunk)
    worker.join(.2);timeout=worker.is_alive()
    if timeout:worker.kill();worker.join(3)
    os.close(rd);records=[];malformed=False
    for line in b''.join(chunks).splitlines():
        try:records.append(json.loads(line))
        except (ValueError,UnicodeError):malformed=True
    events=[r for r in records if r.get('seal') is not True];seals=[r for r in records if r.get('seal') is True]
    transport=not malformed and not limit and len(seals)==1 and seals[0]['dropped']==0 and seals[0]['attempted']==seals[0]['emitted']==len(events) and [r['seq'] for r in events]==list(range(1,len(events)+1))
    complete=not timeout and worker.exitcode==0 and stat.value in [native._SUCCESS,native._FAILED]
    return {'events':events,'seals':seals,'state':{'worker_status':stat.value,'progress':progress.value,'details':[bool(v) for v in details[:]]},'health':{'native_complete':complete,'transport_intact':transport,'semantic_coverage':transport and complete and bool(events)},'source_sha256':hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),'exitcode':worker.exitcode,'outer_timeout':timeout,'wall_seconds':time.monotonic()-start,'observer_limits':{'bytes':16*1024*1024,'seconds':timeout_seconds},'scope':'HumanEval disposition/commitment on two explicitly pinned source files; no hostile evaluator or return-object defense'}
