"""Prospectively frozen original Inspect native-path qualification campaign."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,os.environ.get('ZERORUN_TEST_PACKAGE','/package'))
if __package__:
    from .ordinary import check as ordinary_check
    from .domain import reference_domain,select_records,census
else:
    from ordinary import check as ordinary_check
    from domain import reference_domain,select_records,census
from zerorun_harness.api import canonical,digest
from zerorun_harness.batches import extract_batches
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify
from zerorun_harness.telemetry import capture_native


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,allow_nan=False)
def journal(output,**row):
    with (output/'attempt-ledger.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
def applicable_records(records):
    return [r for r in records if r['evidence_ids'] and r['reasons'] not in
            (['no_applicable_disposition'], ['native_rule_guard_not_applicable'])]


def statuses(result,rule):return [r['status'] for r in applicable_records(result['records']) if r['relationship']==rule]


def mutation_journal(events,health):
    """Mutate the retained raw test copy and its semantic view consistently."""
    result=copy.deepcopy(health)
    by_id={e['id']:e for e in events}
    result['batch_journal']=[copy.deepcopy(by_id[p['id']]) if 'id' in p else p
                             for p in result['batch_journal'] if 'id' not in p or p['id'] in by_id]
    return result


def mutations(profile,material,events,health,binding):
    results=[]
    def checked(values,evidence_health):
        return evaluate(profile,material,values,mutation_journal(values,evidence_health),binding)
    for site,field,rule in [('score-commit','raw','scorer-commit-preserved'),
                           ('raw-consumer','raw','committed-raw-input-preserved'),
                           ('raw-returned','raw','consumer-call-preserved'),
                           ('scored-count','count','filtered-cardinality-preserved')]:
        altered=copy.deepcopy(events)
        e=next(e for e in altered if e['site']==site)
        e['values'][field]=e['values'][field]+' corrupted' if field=='raw' else e['values'][field]+1
        result=checked(altered,health)
        assert 'VIOLATION' in statuses(result,rule)
        results.append(dict(id='wrong-'+site,passed=True,audit=result))
    target=next(e for e in events if e['site']=='score-commit')
    missing=[e for e in events if e['id']!=target['id']]
    result=checked(missing,health)
    assert 'VIOLATION' in statuses(result,'scorer-commit-required')
    results.append(dict(id='missing-real-commit-intact-transport',passed=True,audit=result))
    lossy=copy.deepcopy(health);lossy['transport']={k:False for k in health['transport']}
    result=checked(missing,lossy)
    assert 'INCONCLUSIVE' in statuses(result,'scorer-commit-required')
    assert 'VIOLATION' not in statuses(result,'scorer-commit-required')
    results.append(dict(id='missing-real-commit-known-transport-loss',passed=True,audit=result))
    altered=copy.deepcopy(events)
    e=next(e for e in altered if e['site']=='classification-count' and e['values']['input_size']>0)
    e['values']['count']=0
    result=checked(altered,health)
    assert 'VIOLATION' in statuses(result,'native-unscored-classification')
    results.append(dict(id='native-unscored-count-contradiction',passed=True,audit=result))
    # Every source item and independently frozen membership are retained. Losing
    # only auxiliary end metadata need not defeat another completeness premise.
    auxiliary=copy.deepcopy(health)
    auxiliary['batch_journal']=[p for p in auxiliary['batch_journal'] if not (
        p.get('schema')=='zerorun-native-batch/1' and p['site']=='classification-input' and p['stage']=='end')]
    result=checked(events,auxiliary)
    assert set(statuses(result,'native-unscored-classification'))=={'CONFORMS'}
    results.append(dict(id='frozen-complete-membership-survives-missing-auxiliary-end',passed=True,audit=result))
    # Remove the actual NaN operand from one native input population, not merely
    # its end frame. A remaining numeric subset cannot prove the conjunction.
    victim=next(e for e in events if e['site']=='classification-input' and e['values']['raw']=='NaN'
                and e['identity']['scorer']=='scorer_b')
    missing=[e for e in events if e['id']!=victim['id']]
    lossy['batch_journal']=[p for p in health['batch_journal'] if p.get('id')!=victim['id']]
    result=checked(missing,lossy)
    assert 'INCONCLUSIVE' in statuses(result,'native-unscored-classification')
    results.append(dict(id='lost-actual-nan-operand',passed=True,audit=result))
    return results


def run(fixtures,output):
    fixtures,output=Path(fixtures),Path(output)
    output.mkdir(parents=True,exist_ok=False)
    freeze=json.loads((fixtures/'freeze.json').read_text())
    loaded={n:json.loads((fixtures/(n+'.json')).read_text()) for n in ['profile','binding','cases','inventories','expected-witnesses']}
    profile,binding,cases,inventories,witnesses=[loaded[n] for n in ['profile','binding','cases','inventories','expected-witnesses']]
    for key, value in [('profile_sha256',profile),('case_sha256',cases),('inventory_sha256',inventories),('expected_witnesses_sha256',witnesses)]:
        assert digest(value)==freeze[key]
    assert binding['sha256']==freeze['binding_sha256']
    for name,value in freeze['helper_sha256'].items():assert sha(HERE/name)==value,name
    import zerorun_harness
    core=Path(zerorun_harness.__file__).parent
    for name,value in freeze['core_sha256'].items():assert sha(core/name)==value,name
    controls,retained=[],[]
    for case in cases:
        directory=output/case['id'];directory.mkdir()
        options=dict(fixture_root=str(fixtures),native_root='/native/src',case=case,run='s8-inspect-'+case['id'],
            work='/tmp/'+case['id']+'-reference',call_journal=str(directory/'reference-calls.jsonl'),
            retained_work=str(directory/'reference-artifacts'),raw_reference=str(directory/'reference-raw.json'))
        write(directory/'reference-request.json',options)
        journal(output,case=case['id'],phase='reference-entered',request_sha256=sha(directory/'reference-request.json'))
        start=time.monotonic()
        proc=subprocess.run([sys.executable,'-I',str(HERE/'reference.py'),str(directory/'reference-request.json'),str(directory/'reference.json')],capture_output=True,timeout=90)
        (directory/'reference.stdout.txt').write_bytes(proc.stdout);(directory/'reference.stderr.txt').write_bytes(proc.stderr)
        journal(output,case=case['id'],phase='reference-exit',elapsed_seconds=time.monotonic()-start,returncode=proc.returncode)
        assert proc.returncode==0,(case['id'],proc.stderr.decode(errors='replace'))
        reference=json.loads((directory/'reference.json').read_text())
        options.update(work='/tmp/'+case['id']+'-observed',native_output=str(directory/'observed-native.json'),
            call_journal=str(directory/'observed-calls.jsonl'),retained_work=str(directory/'observed-artifacts'))
        write(directory/'capture-request.json',options)
        journal(output,case=case['id'],phase='observed-entered',request_sha256=sha(directory/'capture-request.json'))
        start=time.monotonic()
        capture=capture_native(str(HERE/'adapter.py'),sha(HERE/'adapter.py'),options,wall_seconds=60)
        write(directory/'capture.json',capture)
        journal(output,case=case['id'],phase='observed-exit',elapsed_seconds=time.monotonic()-start,
            native_complete=capture['health']['native_complete'],transport_intact=capture['health']['transport_intact'])
        assert capture['health']['native_complete'] and capture['health']['transport_intact'],(case['id'],capture)
        assert sha(directory/'observed-native.json')==capture['native']['returned']['output_sha256']
        observed=json.loads((directory/'observed-native.json').read_text())
        assert observed==reference['native'],(case['id'],'stable native outputs or actual callback sequence changed')
        payloads=[packet['event'] for packet in capture['transport']['events']]
        acquired=extract_batches(profile,binding,payloads);write(directory/'batch-acquisition.json',acquired)
        events=acquired['events']
        assert all(b['complete'] for b in acquired['batches'])
        for site in profile['sites']:
            facts=reference['facts'][site]
            assert sorted(canonical(f['identity']) for f in facts)==sorted(canonical(i) for i in witnesses[case['id']][site]),(case['id'],site,'native membership differs from frozen input-side inventory')
            controls.append(dict(id=case['id']+'-'+site,site=site,role='positive' if facts else 'negative',
                reference=dict(source_sha256=sha(HERE/'reference.py'),recipe_sha256=sha(HERE/'native_driver.py'),
                    output_sha256=digest(facts),native_source_sha256=digest(binding['original_sources']),framework_semantics_imported=False,facts=facts),
                observed=[e for e in events if e['site']==site]))
        ordinary=ordinary_check(reference,'/native/src');write(directory/'ordinary.json',ordinary)
        assert all(c['passed'] for c in ordinary['checks'])
        assert all(c['passed'] and c['unique'] for c in ordinary['metric_calls'])
        retained.append((case,directory,reference,capture,events,payloads,acquired))
        print(json.dumps(dict(case=case['id'],stable_native_preserved=True,events=len(events),batches=len(acquired['batches']))),flush=True)
    certificate=qualify(profile,binding,controls);write(output/'qualification.json',certificate)
    assert all(certificate['sites'].values()),certificate['sites']
    touched={(r['path'],r['function'],r['line']) for _,_,ref,*_ in retained for r in ref['traces'] if r['event']=='line'}
    coverage=[{**r,'native_line_executed':(r['path'],r['function'],r['line']) in touched} for r in binding['sites']]
    write(output/'static-coverage.json',coverage);assert all(r['native_line_executed'] for r in coverage)
    rows=[]
    for case,directory,reference,capture,events,payloads,acquired in retained:
        row=dict(case=case['id'],native_eval_calls_per_route=reference['native']['native_calls'],
            authored_scorer_calls_per_route=reference['native']['callback_calls'],native_function_frames=reference['native_function_frames'],
            selected_sync_activations=reference['selected_sync_activations'],events=len(events),batches=len(acquired['batches']),
            empty_batches=sum(b['size']==0 for b in acquired['batches']),stable_native_preserved=True)
        if not case['order']:
            row['qualification_only']=True;rows.append(row);continue
        material=dict(id=case['id'],version='1',inventory=inventories[case['id']],
            source_sha256=digest(binding['original_sources']),input_sha256=digest(case))
        health=dict(binding_sha256=binding['sha256'],sites=certificate['sites'],
            transport={str(capture['producer_pid']):True},native_complete={r['id']:True for r in profile['rules']},
            qualification_sha256=certificate['sha256'],batch_journal=payloads)
        result=evaluate(profile,material,events,health,binding['sha256'])
        write(directory/'case.json',material);write(directory/'health.json',health);write(directory/'audit.json',result)
        domain=reference_domain(profile,reference['facts'])
        write(directory/'native-domain.json',census(result['records'],domain))
        relevant=select_records(result['records'],domain)
        assert relevant and all(r['status']=='CONFORMS' for r in relevant),(case['id'],[r for r in relevant if r['status']!='CONFORMS'])
        fault_controls=[] if case.get('empty_scores') else mutations(profile,material,events,health,binding['sha256'])
        write(directory/'mutation-controls.json',fault_controls)
        row.update(passed=True,applicable_relationships=len(relevant),excluded_products=len(result['records'])-len(relevant),
            excluded_empty_native_guard=sum(r['reasons']==['native_rule_guard_not_applicable'] for r in result['records']),
            vacuous_no_disposition_products=sum(r['reasons']==['no_applicable_disposition'] for r in result['records']),
            mutation_controls=len(fault_controls),declared_inventory_entries=len(material['inventory']))
        rows.append(row)
    summary=dict(passed=True,rows=rows,cases=len(rows),logical_views=len(profile['sites']),static_source_matches=len(binding['sites']),
        python=sys.version,uid=os.getuid(),freeze_sha256=sha(fixtures/'freeze.json'),primary_candidate_calls=0,
        scope='Original Inspect eval score commit and raw/reduced consumer development qualification; stable declared fields, complete logs retained')
    write(output/'summary.json',summary);print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':run(sys.argv[1],sys.argv[2])
