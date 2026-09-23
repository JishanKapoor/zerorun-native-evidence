"""Standalone native export executions and comparison, no framework import."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def load(path):
    return json.loads(path.read_text())


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2)


def run(prepared,output):
    output.mkdir(parents=True,exist_ok=False)
    design=load(prepared/'design.json')
    for name,expected in design['files'].items():
        if hashlib.sha256((prepared/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen export source changed: '+name)
    rows=[]
    for control in design['cases']:
        case=output/control['id']
        case.mkdir()
        source=prepared/control['id']
        command=[sys.executable,'-I',str(source/'regression.py'),'--source',str(source/'source'),'--output',str(case/'native-export.json')]
        start=time.monotonic()
        process=subprocess.run(command,cwd=case,capture_output=True,timeout=20)
        (case/'stdout.txt').write_bytes(process.stdout)
        (case/'stderr.txt').write_bytes(process.stderr)
        save(case/'command.json',dict(argv=command,cwd=str(case),returncode=process.returncode,
                                     wall_seconds=time.monotonic()-start,
                                     stdout_sha256=hashlib.sha256(process.stdout).hexdigest(),
                                     stderr_sha256=hashlib.sha256(process.stderr).hexdigest()))
        native=load(case/'native-export.json')
        reference=load(case/'native-reference/reference.json')
        primary=load(source/'expected-primary.json')
        key=lambda row:(row['relationship'],json.dumps(row['identity'],sort_keys=True))
        mapping={'CONFORMS':'PASS','VIOLATION':'FAIL','INCONCLUSIVE':'UNASSESSABLE','UNSUPPORTED':'UNASSESSABLE'}
        expected={key(row):mapping[row['status']] for row in primary['records']}
        actual={key(row):row['result'] for row in native.get('assertions',[])}
        checks=dict(exact_assertion_inventory=len(native.get('assertions',[]))==len(expected)==control['expected_assertion_count'],
                    matches_primary=actual==expected,
                    no_framework=native['classification_dependency'] is False and reference['framework_semantics_imported'] is False,
                    one_original_native_bank=reference['native_bank_calls']==1,
                    one_recipe_call=native['native_calls']==1,
                    expected_process_disposition=process.returncode=={'PASS':0,'FAIL':1,'UNASSESSABLE':2}.get(native['result']))
        mismatches=[dict(relationship=k[0],identity=json.loads(k[1]),primary=expected.get(k),native=actual.get(k)) for k in sorted(expected.keys()|actual.keys()) if expected.get(k)!=actual.get(k)]
        rows.append(dict(case=control['id'],checks=checks,passed=all(checks.values()),native_bank_calls=reference['native_bank_calls'],
                         assertion_records=len(actual),mismatches=mismatches,
                         result=native['result'],scope='Includes inventory products; not a scientific effect denominator'))
    report=dict(schema='s8-evalplus-standalone-export-qualification/1',passed=all(row['passed'] for row in rows),
                native_bank_calls=sum(row['native_bank_calls'] for row in rows),controls=rows,
                scope='Four actual original bank invocations; zero framework imports in each standalone execution; exposed engineering only')
    save(output/'summary.json',report)
    return report


if __name__=='__main__':
    report=run(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
