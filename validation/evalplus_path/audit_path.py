"""Read-only raw receipt reconciliation; no framework imports or native calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def canon(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def audit(prepared,campaign):
    design=load(prepared/'design.json')
    checks=[]
    def record(name,passed,**detail):
        checks.append(dict(check=name,passed=bool(passed),**detail))
    for name,expected in design['files'].items():
        record('frozen_file',hashlib.sha256((prepared/name).read_bytes()).hexdigest()==expected,path=name)
    total_cases=bank_calls=control_count=bound_sites=0
    for variant in design['sources']:
        vid=variant['id']
        profile=load(prepared/vid/'profile.json')
        binding=load(prepared/vid/'binding.json')
        certificate=load(campaign/vid/'qualification.json')
        control_count+=len(certificate['controls'])
        bound_sites+=len(binding['sites'])
        raw_seen=[]
        certificate_controls={row['id']:row for row in certificate['controls']}
        for case in load(prepared/vid/'controls.json'):
            cid=case['id']
            path=campaign/vid/cid
            original=load(path/'reference/reference.json')
            observed=load(path/'capture.json')
            preserved=load(path/'preservation.json')
            total_cases+=1
            bank_calls+=original['native_bank_calls']+int(observed['graph']['worker_required'])
            record('native_result_preserved',original['returned']==observed['native']['returned'] and original['exception']==observed['native']['exception'],case=vid+':'+cid)
            facts=original['journal']['parent']+original['journal']['worker']
            raw_seen.extend(facts)
            payloads=[row['event'] for role in ('parent','worker') for row in observed['transport'][role]['events']]
            events=[row for row in payloads if row.get('schema')=='zerorun-native-fact/1']
            # Semantic schema is versioned by common recorder. If its known name
            # differs, use exact structural identity admitted in this design.
            if not events:
                events=[row for row in payloads if 'site' in row and 'kind' in row and 'values' in row and 'id' in row]
            for role in ('parent','worker'):
                journal=original['journal'][role]
                record('reference_local_sequence', [r['sequence'] for r in journal]==list(range(1,len(journal)+1)),case=vid+':'+cid,role=role)
                packets=observed['transport'][role]['events']
                record('actual_producer_identity',all(row['producer']==observed['graph'][role+'_pid'] for row in packets),case=vid+':'+cid,role=role)
            for site in profile['sites']:
                raw=[dict(identity=row['identity'],values=row['values']) for row in facts if row['name']==site]
                actual=[dict(identity=row['identity'],values=row['values']) for row in events if row['site']==site]
                retained=certificate_controls[cid+':'+site]
                record('raw_reference_vs_actual_site',Counter(map(canon,raw))==Counter(map(canon,actual)),case=vid+':'+cid,site=site)
                record('certificate_retains_raw_control',retained['reference']['facts']==raw and Counter(map(canon,retained['observed']))==Counter(map(canon,[e for e in events if e['site']==site])),case=vid+':'+cid,site=site)
            if observed['graph']['worker_required']:
                snapshots=observed['graph']['buffers']
                record('same_invocation_buffer_objects',snapshots['matched'] is True and snapshots['parent']==snapshots['worker'],case=vid+':'+cid)
                record('native_fork_pid_graph',observed['graph']['parent_pid']==observed['graph']['worker_parent_pid'] and observed['graph']['worker_pid']==observed['graph']['expected_worker_pid'] and observed['graph']['parent_pid']!=observed['graph']['worker_pid'],case=vid+':'+cid)
            for native_name,site in [('native-materialized-batch','parent-materialized-details'),('native-returned-batch','parent-returned-details')]:
                native_batches=[r for r in facts if r['name']==native_name]
                batch_events=[r for r in events if r['site']==site]
                controls=[r for r in payloads if r.get('schema')=='zerorun-native-batch/1' and r['site']==site]
                if native_batches:
                    values=[r['values']['stored'] for r in sorted(batch_events,key=lambda row:row['identity']['obligation'])]
                    record('actual_native_batch_elements',len(native_batches)==1 and values==native_batches[0]['values']['details'],case=vid+':'+cid,site=site)
                    record('batch_boundaries_match_native_size',len(controls)==2 and {r['stage'] for r in controls}=={'begin','end'} and all(r['size']==len(values) for r in controls),case=vid+':'+cid,site=site)
                else:
                    record('absent_native_batch_not_invented',not batch_events and not controls,case=vid+':'+cid,site=site)
        for site in binding['sites']:
            matches=[row for row in raw_seen if row['name']==site['site'] and
                     (row['source_line']==site['line'] or site['position']=='handler_entry' and site['line']<=row['source_line']<=site['end_line'])]
            record('physical_native_anchor_visited',bool(matches),variant=vid,site=site['site'],line=site['line'],witnesses=len(matches))
        record('declared_sites_qualified',all(certificate['sites'].values()),variant=vid)
    summary=load(campaign/'summary.json')
    record('bank_call_inventory',bank_calls==design['native_bank_calls']==summary['native_bank_calls'])
    record('raw_qualification_control_count',control_count==summary['qualification_controls'])
    record('applicable_denominator_partition',summary['total_inventory_relationships']==summary['applicable_relationships']+summary['excluded_inventory_products'])
    return dict(schema='s8-evalplus-independent-receipt-audit/1',passed=all(row['passed'] for row in checks),
                cases=total_cases,native_bank_calls_retained=bank_calls,new_native_calls=0,
                physical_binding_sites=bound_sites,qualification_controls=control_count,
                checks=checks,check_count=len(checks),failures=[r for r in checks if not r['passed']],
                scope='Independent mechanical raw receipt reconciliation; no new native execution, human independence, chronology or publication approval')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepared',type=Path,required=True)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.prepared,args.campaign)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},indent=2))
    raise SystemExit(0 if report['passed'] else 1)
