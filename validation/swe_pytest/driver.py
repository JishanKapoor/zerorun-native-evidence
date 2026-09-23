"""Actual pytest invocation and closed stdout handoff to original SWE APIs."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pytest_native.fixtures import TEST_SOURCE,EXPECTED
from pytest_native.native import NativeReference


def write_json(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)


def execute_pytest(native,case,run,work,output,*,acquisition_plugins=()):
    work,output=Path(work),Path(output)
    work.mkdir(parents=True,exist_ok=False)
    (work/'test_native_controls.py').write_text(TEST_SOURCE,encoding='utf-8',newline='\n')
    (work/'pytest.ini').write_text('[pytest]\n',encoding='utf-8')
    reference=NativeReference(output/'pytest-native-reports.jsonl',run=run,attempt=case['attempt'])
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    os.environ.pop('PYTEST_ADDOPTS',None)
    with (output/'pytest-calls.jsonl').open('a',encoding='utf-8') as journal:
        journal.write(json.dumps(dict(event='entered',operation='pytest.main',run=run,attempt=case['attempt']))+'\n')
    old=Path.cwd()
    try:
        os.chdir(work)
        with (output/'pytest.stdout.txt').open('x',encoding='utf-8',newline='\n') as stdout, (output/'pytest.stderr.txt').open('x',encoding='utf-8',newline='\n') as stderr:
            with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                status=native.main(['-c','pytest.ini','--confcutdir',str(work),'-p','no:cacheprovider','-o','addopts=',
                    '-rA','-vv','--tb=short','--color=no','test_native_controls.py'],plugins=[reference,*acquisition_plugins])
    finally:
        os.chdir(old)
    with (output/'pytest-calls.jsonl').open('a',encoding='utf-8') as journal:
        journal.write(json.dumps(dict(event='returned',operation='pytest.main',exitstatus=int(status)))+'\n')
    reports=[json.loads(line) for line in (output/'pytest-native-reports.jsonl').read_text(encoding='utf-8').splitlines()]
    # The genuine terminal stream stays byte-for-byte intact. Marker lines are
    # separate, explicitly disclosed SWE acquisition framing, not pytest output.
    raw=(output/'pytest.stdout.txt').read_bytes()
    framed=b'>>>>> Start Test Output\n'+raw+b'\n>>>>> End Test Output\n'
    (output/'swe-acquisition-input.txt').write_bytes(framed)
    provenance=dict(stdout_sha256=hashlib.sha256(raw).hexdigest(),stdout_bytes=len(raw),
        framed_sha256=hashlib.sha256(framed).hexdigest(),framed_bytes=len(framed),
        body_offset=len(b'>>>>> Start Test Output\n'),source='Actual closed pytest stdout only; stderr separately retained',
        run=run,attempt=case['attempt'],native_exitstatus=int(status))
    write_json(output/'artifact-provenance.json',provenance)
    if int(status)!=1:raise ValueError('Authored native failure controls must produce pytest exit code1')
    actual=[r for r in reports if r['event']=='test_report']
    expected=[(name,phase,outcome) for name,rows in EXPECTED.items() for phase,outcome in rows]
    if [(r['nodeid'].split('::',1)[1],r['when'],r['outcome']) for r in actual]!=expected:
        raise ValueError('Actual native phase/report inventory differs from frozen authored input')
    item=dict(id='a',log=framed.decode('utf-8'),
              fail_to_pass=['test_native_controls.py::test_pass'],
              pass_to_pass=['test_native_controls.py::test_parameter[one]'])
    swe_case=dict(id=case['id'],instances=[item])
    return dict(pytest_status=int(status),reports=reports,provenance=provenance),swe_case


def stable_swe(native):
    # Real terminal timings/paths in the raw acquired input differ across runs.
    # Original SWE returns and report serialization remain exact comparisons.
    return dict(operations=native['operations'],
        report_artifacts={k:v for k,v in native['artifacts'].items() if k.endswith('.json')},
        closed_writer_artifacts=native['closed_writer_artifacts'])
