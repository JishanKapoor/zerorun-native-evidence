"""Exposed native transport controls. Return values are fixed outside telemetry."""
import hashlib
import importlib
import os
from pathlib import Path
import sys
import time


def run(emitter,argument):
    mode=argument['mode']
    if mode=='native_guard':
        source=Path(argument['source'])
        p=source/'evalplus/eval/utils.py'
        if hashlib.sha256(p.read_bytes()).hexdigest()!=argument['guard_sha256']:raise RuntimeError('Guard source mismatch')
        sys.path.insert(0,str(source))
        native=importlib.import_module('evalplus.eval.utils')
        native.reliability_guard()
    if mode=='stdio':
        print('NATIVE_STDOUT',flush=True)
        print('NATIVE_STDERR',file=sys.stderr,flush=True)
    if mode=='broken_fd':os.close(emitter.fd)
    if mode=='missing_seal':emitter.seal=lambda:False
    if mode=='partial_frame':
        write=emitter._write
        emitter._write=lambda fd,data:write(fd,data[:7])
        emitter.emit({'native_fact':True})
        emitter._write=write
    elif mode=='corrupt_frame':
        write=emitter._write
        emitter._write=lambda fd,data:write(fd,data[:8]+bytes([data[8]^1])+data[9:])
        emitter.emit({'native_fact':True})
        emitter._write=write
    elif mode=='bad_callback':
        class UnsupportedNativeObject:
            def __repr__(self):raise AssertionError('candidate repr called')
            def __reduce__(self):raise AssertionError('candidate pickle called')
        emitter.emit(UnsupportedNativeObject())
    elif mode=='silent_callback':pass
    else:
        for i in range(5000 if mode in ('flood','trace_cap') else 2):
            emitter.emit({'native_fact':True,'index':i})
    if mode=='native_timeout':raise TimeoutError('independent native timeout control')
    if mode=='native_termination':raise SystemExit(7)
    if mode=='native_interrupt':raise KeyboardInterrupt()
    if mode=='deadline':time.sleep(2)
    if mode=='timing_boundary':time.sleep(.02)
    return {'native_value':17,'native_marker':'unchanged'}
