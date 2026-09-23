"""Pinned-file original/observed large-bank acquisition; no truncated inputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0,str(Path(__file__).resolve().parent/'implementation'))
from campaign import health, arithmetic
from expectations import applicable
from zerorun_harness.api import digest
from zerorun_harness._telemetry_multiprocess import capture_native_pair
from zerorun_harness.batches import extract_batches
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify


def load(path):
    return json.loads(path.read_text())


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(prepared,output):
    output.mkdir(parents=True,exist_ok=False)
    design=load(prepared/'design.json')
    for name,expected in design['files'].items():
        if sha(prepared/name)!=expected:
            raise ValueError('Frozen large bank preparation changed: '+name)
    adapter=prepared/'implementation/adapter.py'
    reference_script=prepared/'implementation/reference.py'
    rows=[]
    for control in design['controls']:
        result=output/control['id']
        result.mkdir()
        native_path=prepared/control['case_path']
        native_case=load(native_path)
        revision=control['revision']
        root=prepared/revision
        profile,binding=load(root/'profile.json'),load(root/'binding.json')
        run_id=revision+':'+native_case['id']
        command=[sys.executable,'-I',str(reference_script),str(root),str(native_path),str(result/'reference'),run_id]
        start=time.monotonic()
        original=subprocess.run(command,capture_output=True,timeout=30)
        (result/'reference.stdout.txt').write_bytes(original.stdout)
        (result/'reference.stderr.txt').write_bytes(original.stderr)
        save(result/'reference-command.json',dict(argv=command,returncode=original.returncode,wall_seconds=time.monotonic()-start))
        if original.returncode:
            raise RuntimeError('Original large native reference failed')
        reference=load(result/'reference/reference.json')
        argument=dict(prepared=str(root),case_path=str(native_path),case_sha256=control['case_sha256'],run=run_id,
                      native_result_path=str(result/'observed-native-result.json'))
        save(result/'capture-request.json',argument)
        capture=capture_native_pair(adapter,sha(adapter),argument,wall_seconds=30)
        save(result/'capture.json',capture)
        if 'transport' not in capture or not (result/'observed-native-result.json').is_file():
            raise RuntimeError('Observed large native result unavailable')
        actual=load(result/'observed-native-result.json')
        returned=capture['native']['returned']
        payloads=[packet['event'] for role in ('parent','worker') for packet in capture['transport'][role]['events']]
        extracted=extract_batches(profile,binding,payloads)
        save(result/'batch-acquisition.json',extracted)
        facts=reference['journal']['parent']+reference['journal']['worker']
        observations=extracted['events']
        controls=list(load(root/'prior-qualification.json')['controls'])
        for site in profile['sites']:
            raw=[dict(identity=row['identity'],values=row['values']) for row in facts if row['name']==site]
            controls.append(dict(id=native_case['id']+':'+site,site=site,role='positive' if raw else 'negative',
                reference=dict(source_sha256=sha(reference_script),recipe_sha256=reference['recipe_sha256'],
                               output_sha256=digest(raw),native_source_sha256=digest(binding['original_sources']),
                               framework_semantics_imported=reference['framework_semantics_imported'],facts=raw),
                observed=[event for event in observations if event['site']==site]))
        qualification=qualify(profile,binding,controls)
        save(result/'qualification.json',qualification)
        material=dict(id=run_id,version='1.0.0',inventory=[dict(run=run_id,candidate=native_case['id'],obligation=i,phase='base',attempt=1)
                      for i in range(len(native_case['inputs']))],source_sha256=digest(binding['original_sources']),input_sha256=digest(native_case))
        h=health(profile,binding,qualification,capture,payloads)
        audit=evaluate(profile,material,observations,h,binding['sha256'])
        save(result/'case.json',material)
        save(result/'health.json',h)
        save(result/'audit.json',audit)
        selected=applicable(profile,audit,observations,extracted['batches'],reference)
        native_batches=[row for row in facts if row['name'] in ('native-materialized-batch','native-returned-batch')]
        batch_checks=[]
        for native_name,site in [('native-materialized-batch','parent-materialized-details'),('native-returned-batch','parent-returned-details')]:
            raw=[row for row in native_batches if row['name']==native_name]
            batches=[b for b in extracted['batches'] if b['site']==site]
            values=[row['values']['stored'] for row in sorted([e for e in observations if e['site']==site],key=lambda e:e['identity']['obligation'])]
            batch_checks.append(len(raw)==len(batches)==1 and batches[0]['complete'] and batches[0]['size']==control['inputs'] and values==raw[0]['values']['details'])
        checks=dict(native_result_preserved=actual==reference['returned'] and capture['native']['exception']==reference['exception'],
                    result_bytes_pinned=sha(result/'observed-native-result.json')==returned['native_result_sha256'],
                    full_native_population=returned['details_count']==control['inputs']==len(actual['details']),
                    sites_qualified=all(qualification['sites'].values()),
                    native_batches_exact=all(batch_checks),same_buffers=capture['graph']['buffers']['matched'] is True,
                    both_producers_complete=all(x['complete'] for x in capture['lifecycle'].values()),
                    both_transports_intact=all(x['transport_intact'] is True for x in capture['transport'].values()),
                    applicable_all_conform=all(row['status']=='CONFORMS' for row in selected),
                    exact_progress_arithmetic=arithmetic(reference)['completed_count'],
                    original_bank_called_once=reference['native_bank_calls']==1,observed_bank_called_once=capture['graph']['fork_attempts']==1)
        counts={role:dict(received_bytes=receipt['received_bytes'],stored_events=receipt['stored_events'],errors=receipt['errors']) for role,receipt in capture['transport'].items()}
        rows.append(dict(case=control['id'],inputs=control['inputs'],checks=checks,passed=all(checks.values()),
                         native_bank_calls=reference['native_bank_calls']+int(capture['graph']['worker_required']),
                         trace=counts,budget=control['budget'],semantic_events=len(observations),
                         new_site_controls=len(profile['sites']),prior_controls=len(controls)-len(profile['sites']),
                         relationships=len(audit['records']),applicable_relationships=len(selected),
                         excluded_inventory_products=len(audit['records'])-len(selected),
                         applicable_status_counts=dict(Counter(row['status'] for row in selected))))
        save(result/'checks.json',rows[-1])
    report=dict(schema='s8-evalplus-large-bank-qualification/1',passed=all(row['passed'] for row in rows),
                controls=rows,native_bank_calls=sum(row['native_bank_calls'] for row in rows),
                retained_dataset_count_review=design['retained_dataset_count_review'],
                scope='Authored128/1000-input capacity qualification with full native populations; no cohort results/participant or arbitrary size claim')
    save(output/'summary.json',report)
    return report


if __name__=='__main__':
    report=run(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
