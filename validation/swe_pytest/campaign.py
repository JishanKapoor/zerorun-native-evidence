"""Real pytest -> original SWE parser/grading/writer/reader, one acquisition."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
sys.path.insert(0,os.environ.get('ZERORUN_TEST_PACKAGE','/package'))
from swe_pytest.driver import write_json
from swe_pytest.bridge import audit as bridge_audit,verify_audit_outcomes,applicable_records
from swe_pytest.domain import reference_domain,select_records,census
from zerorun_harness.api import canonical,digest
from zerorun_harness.declarative import evaluate
from zerorun_harness.qualification import qualify,validate_qualification
from zerorun_harness.telemetry import capture_native
import zerorun_harness


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def journal(output,**row):
    with (output/'attempt-ledger.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row)+'\n')
def matches(facts,events):
    return sorted(canonical(f) for f in facts)==sorted(canonical(dict(identity=e['identity'],values=e['values'])) for e in events)


def run(fixtures,output):
    fixtures,output=Path(fixtures),Path(output);output.mkdir(parents=True,exist_ok=False)
    freeze=json.loads((fixtures/'freeze.json').read_text());cases=json.loads((fixtures/'cases.json').read_text())
    inventory=json.loads((fixtures/'inventories.json').read_text())
    expected_ambiguities=json.loads((fixtures/'expected-ambiguities.json').read_text())
    assert digest(cases)==freeze['cases_sha256'] and digest(inventory)==freeze['inventories_sha256']
    assert digest(expected_ambiguities)==freeze['expected_ambiguities_sha256']
    for relative,value in freeze['source_files'].items():
        core_root=Path(zerorun_harness.__file__).resolve().parent.parent
        path=core_root/relative.removeprefix('src/') if relative.startswith('src/') else HERE.parents[1]/relative
        assert sha(path)==value,relative
    py_profile=json.loads((fixtures/'pytest-profile.json').read_text());py_binding=json.loads((fixtures/'pytest-binding.json').read_text())
    controls=[];retained=[]
    for case in cases:
        folder=output/case['id'];folder.mkdir();version=case['version'];frozen=fixtures/version
        sp=json.loads((frozen/'swe-profile.json').read_text());sb=json.loads((frozen/'swe-binding.json').read_text())
        sq=json.loads((frozen/'swe-prior-qualification.json').read_text());validate_qualification(sp,sb,sq)
        options=dict(fixture_root=str(fixtures),case=case,run='s8-pytest-'+case['id'],native_root='/native_'+version,
            work='/tmp/'+case['id']+'-reference',route_output=str(folder/'reference'))
        write_json(folder/'reference-request.json',options);journal(output,case=case['id'],phase='reference-entered')
        start=time.monotonic()
        proc=subprocess.run([sys.executable,'-I',str(HERE/'reference.py'),str(folder/'reference-request.json'),str(folder/'reference.json')],capture_output=True,timeout=75)
        (folder/'reference.stdout.txt').write_bytes(proc.stdout);(folder/'reference.stderr.txt').write_bytes(proc.stderr)
        journal(output,case=case['id'],phase='reference-exit',elapsed_seconds=time.monotonic()-start,returncode=proc.returncode)
        assert proc.returncode==0,(case['id'],proc.stderr.decode(errors='replace'))
        reference=json.loads((folder/'reference.json').read_text())
        options.update(work='/tmp/'+case['id']+'-observed',route_output=str(folder/'observed'))
        write_json(folder/'capture-request.json',options);journal(output,case=case['id'],phase='observed-entered')
        start=time.monotonic();capture=capture_native(str(HERE/'adapter.py'),sha(HERE/'adapter.py'),options,wall_seconds=60)
        write_json(folder/'capture.json',capture)
        journal(output,case=case['id'],phase='observed-exit',elapsed_seconds=time.monotonic()-start,
            native_complete=capture['health']['native_complete'],transport_intact=capture['health']['transport_intact'])
        assert capture['health']['native_complete'] and capture['health']['transport_intact'],(case['id'],capture)
        observed=json.loads((folder/'observed/native.json').read_text());assert sha(folder/'observed/native.json')==capture['native']['returned']['output_sha256']
        if not case.get('no_call'):
            assert observed['pytest']['reports']==reference['native']['pytest']['reports']
            assert observed['stable_swe']==reference['native']['stable_swe'],(case['id'],'native SWE reports differ')
            assert all(r['exception'] is None for r in observed['swe']['operations'])
        else:assert observed==reference['native']
        payloads=[p['event'] for p in capture['transport']['events']]
        py_events=[e for e in payloads if e.get('binding_sha256')==py_binding['sha256']]
        swe_events=[e for e in payloads if e.get('binding_sha256')==sb['sha256']]
        assert len(py_events)+len(swe_events)==len(payloads)
        for site in py_profile['sites']:
            facts=reference['pytest_facts'][site]
            expected=inventory[case['id']]['pytest']
            assert sorted(canonical(f['identity']) for f in facts)==sorted(canonical(i) for i in expected),(case['id'],site,'prospective phase population differs')
            controls.append(dict(id=case['id']+'-'+site,site=site,role='positive' if facts else 'negative',
                reference=dict(source_sha256=sha(HERE/'reference.py'),recipe_sha256=sha(HERE/'driver.py'),output_sha256=digest(facts),
                    native_source_sha256=digest(py_binding['original_sources']),framework_semantics_imported=False,facts=facts),
                observed=[e for e in py_events if e['site']==site]))
        swe_comparison={site:matches(reference['swe_facts'][site],[e for e in swe_events if e['site']==site]) for site in sp['sites']}
        write_json(folder/'swe-original-observed-site-equality.json',swe_comparison);assert all(swe_comparison.values()),swe_comparison
        bridge=bridge_audit(reference,folder/'reference');write_json(folder/'native-bridge.json',bridge)
        if not case.get('no_call'):
            assert all(bridge['artifact_checks'].values())
            observed_reference=dict(native=observed,pytest_facts={s:[dict(identity=e['identity'],values=e['values']) for e in py_events if e['site']==s] for s in py_profile['sites']},
                swe_facts={s:[dict(identity=e['identity'],values=e['values']) for e in swe_events if e['site']==s] for s in sp['sites']})
            observed_bridge=bridge_audit(observed_reference,folder/'observed');write_json(folder/'observed-native-bridge.json',observed_bridge)
            assert all(observed_bridge['artifact_checks'].values())
            assert observed_bridge['native_phase_attribution']==bridge['native_phase_attribution']
        retained.append((case,folder,reference,capture,py_events,swe_events,sp,sb,sq))
        print(json.dumps(dict(case=case['id'],native_preserved=True,pytest_events=len(py_events),swe_events=len(swe_events))),flush=True)
    pq=qualify(py_profile,py_binding,controls);write_json(output/'pytest-qualification.json',pq)
    assert all(pq['sites'].values()),pq['sites']
    touched={(r['path'],r['function'],r['line']) for _,_,ref,*_ in retained for r in ref['pytest_traces'] if r['event']=='line'}
    coverage=[{**r,'native_line_executed':(r['path'],r['function'],r['line']) in touched} for r in py_binding['sites']]
    write_json(output/'pytest-static-coverage.json',coverage);assert all(r['native_line_executed'] for r in coverage)
    rows=[]
    for case,folder,reference,capture,pe,se,sp,sb,sq in retained:
        row=dict(case=case['id'],pytest_api_calls_per_route=0 if case.get('no_call') else 1,swe_api_calls_per_route=0 if case.get('no_call') else 2,
                 native_reports_per_route=0 if case.get('no_call') else 28,pytest_events=len(pe),swe_events=len(se))
        if case.get('no_call'):row['qualification_only']=True;rows.append(row);continue
        for name,p,b,q,events in [('pytest',py_profile,py_binding,pq,pe),('swe',sp,sb,sq,se)]:
            material=dict(id=case['id']+'-'+name,version='1',inventory=inventory[case['id']][name],source_sha256=digest(b['original_sources']),input_sha256=digest(case))
            health=dict(binding_sha256=b['sha256'],sites=q['sites'],transport={str(capture['producer_pid']):True},
                native_complete={r['id']:True for r in p['rules']},qualification_sha256=q['sha256'])
            result=evaluate(p,material,events,health,b['sha256'])
            for suffix,value in [('case',material),('health',health),('audit',result)]:write_json(folder/(name+'-'+suffix+'.json'),value)
            domain=reference_domain(p,reference[name+'_facts'])
            write_json(folder/(name+'-native-domain.json'),census(result['records'],domain))
            relevant=select_records(result['records'],domain)
            verify_audit_outcomes(relevant,expected_ambiguities[case['id']] if name=='swe' else [])
            row[name]=dict(applicable=len(relevant),excluded=len(result['records'])-len(relevant),
                conforms=sum(r['status']=='CONFORMS' for r in relevant),
                expected_ambiguity=sum(r['status']=='INCONCLUSIVE' for r in relevant),
                vacuous=sum(r['reasons']==['no_applicable_disposition'] for r in result['records']))
        row.update(passed=True,phase_ambiguity_preserved=True);rows.append(row)
    summary=dict(passed=True,rows=rows,pytest_logical_views=5,pytest_static_matches=5,
        python=sys.version,uid=os.getuid(),freeze_sha256=sha(fixtures/'freeze.json'),primary_candidate_calls=0,
        scope='Actual authored pytest phases to original saved-log SWE parser/grading/writer/reader in one capture; no patched benchmark repository or upstream retry claim')
    write_json(output/'summary.json',summary);print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':run(sys.argv[1],sys.argv[2])
