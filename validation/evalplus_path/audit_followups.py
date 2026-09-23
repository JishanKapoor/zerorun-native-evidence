"""Independent retained raw audit of native exports and large input banks."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def run(large_prepared, large_campaign, export_prepared, export_campaign):
    checks=[]
    def check(name,value,**details):
        checks.append(dict(check=name,passed=bool(value),**details))
    for folder,preparation in (('exports',export_prepared),('large',large_prepared)):
        for name,expected in load(preparation/'design.json')['files'].items():
            check('frozen_followup_file',sha(preparation/name)==expected,preparation=folder,path=name)
    large=large_campaign
    design=load(large_prepared/'design.json')
    calls=0
    novel_controls=0
    inputs=0
    for control in design['controls']:
        directory=large/control['id']
        capture=load(directory/'capture.json')
        reference=load(directory/'reference/reference.json')
        raw=reference['journal']['parent']+reference['journal']['worker']
        q=load(directory/'qualification.json')
        p=load(large_prepared/control['revision']/'profile.json')
        payloads=[packet['event'] for role in ('parent','worker') for packet in capture['transport'][role]['events']]
        events=[event for event in payloads if all(key in event for key in ('kind','site','values','id','identity'))]
        case=load(large_prepared/control['case_path'])
        banklen=control['inputs']
        inputs+=banklen
        calls+=reference['native_bank_calls']+int(capture['graph']['worker_required'])
        for site in p['sites']:
            expected=[dict(identity=row['identity'],values=row['values']) for row in raw if row['name']==site]
            actual=[dict(identity=row['identity'],values=row['values']) for row in events if row['site']==site]
            check('large_native_site_exact_multiset',Counter(map(canonical,expected))==Counter(map(canonical,actual)),case=control['id'],site=site)
            retained=[row for row in q['controls'] if row['id']==case['id']+':'+site]
            check('retained_new_site_reference',len(retained)==1 and retained[0]['reference']['facts']==expected,case=control['id'],site=site)
            novel_controls+=1
        for role in ('parent','worker'):
            transport=capture['transport'][role]
            check('actual_trace_below_declared_bound',transport['received_bytes']<=control['budget']['wire_bytes_upper'][role]<=control['budget']['max_trace_bytes']//2,case=control['id'],role=role)
            check('per_producer_transport_complete',transport['transport_intact'] is True and transport['errors']==[] and capture['lifecycle'][role]['complete'] is True,case=control['id'],role=role)
            check('fresh_actual_producer_sequence',[r['seq'] for r in transport['events']]==list(range(1,len(transport['events'])+1)) and all(r['producer']==capture['graph'][role+'_pid'] for r in transport['events']),case=control['id'],role=role)
        check('complete_semantic_inventory',len(events)==6*banklen+6==control['budget']['semantic_events_upper']<16384,case=control['id'])
        original=reference['returned']
        actual=load(directory/'observed-native-result.json')
        check('large_native_result_bytes_and_elements',original==actual and len(actual['details'])==banklen and sha(directory/'observed-native-result.json')==capture['native']['returned']['native_result_sha256'],case=control['id'])
        for site in ('parent-materialized-details','parent-returned-details'):
            elements=sorted([row for row in events if row['site']==site],key=lambda r:r['identity']['obligation'])
            check('all_native_element_identities_present',[row['identity']['obligation'] for row in elements]==list(range(banklen)) and [row['values']['stored'] for row in elements]==original['details'],case=control['id'],site=site)
        rejected=[row for row in raw if row['name']=='caught-rejection']
        false_writes=[row for row in raw if row['name']=='false-commit']
        loops=[row for row in raw if row['name']=='worker-loop-completed']
        check('rejections_with_actual_loop_completion',len(rejected)==len(false_writes)==banklen//2 and len(loops)==1 and all(row['proof']=='completed_STORE_SUBSCR' for row in false_writes),case=control['id'])
    exports=export_campaign
    exported_calls=0
    exported_assertions=0
    for control in load(export_prepared/'design.json')['cases']:
        directory=exports/control['id']
        result=load(directory/'native-export.json')
        native=load(directory/'native-reference/reference.json')
        expected=load(export_prepared/control['id']/'expected-primary.json')
        transform={'CONFORMS':'PASS','VIOLATION':'FAIL','INCONCLUSIVE':'UNASSESSABLE','UNSUPPORTED':'UNASSESSABLE'}
        key=lambda r:(r['relationship'],canonical(r['identity']))
        check('standalone_exact_native_assertions',{key(r):r['result'] for r in result['assertions']}=={key(r):transform[r['status']] for r in expected['records']},case=control['id'])
        check('standalone_did_not_import_framework',result['classification_dependency'] is False and native['framework_semantics_imported'] is False,case=control['id'])
        check('standalone_real_original_bank',native['native_bank_calls']==result['native_calls']==1 and len([row for row in native['journal']['parent'] if row['name']=='native-child-started'])==1,case=control['id'])
        exported_calls+=native['native_bank_calls']
        exported_assertions+=len(result['assertions'])
    return dict(schema='s8-evalplus-followup-raw-audit/1',passed=all(row['passed'] for row in checks),
                check_count=len(checks),checks=checks,failures=[row for row in checks if not row['passed']],
                large_original_observed_bank_calls=calls,large_scenario_input_positions=inputs,
                large_original_observed_input_visits=2*inputs,generated_model_outputs=0,
                large_new_site_controls=novel_controls,standalone_bank_calls=exported_calls,
                standalone_inventory_assertions=exported_assertions,new_native_calls=0,
                scope='Stdlib-only independent mechanical reconciliation; no participant, historical-chronology or scientific-effect denominator claim')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--large-prepared',type=Path,required=True)
    parser.add_argument('--large-campaign',type=Path,required=True)
    parser.add_argument('--export-prepared',type=Path,required=True)
    parser.add_argument('--export-campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run(args.large_prepared,args.large_campaign,args.export_prepared,args.export_campaign)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2)
    print(json.dumps({key:value for key,value in report.items() if key!='checks'},indent=2))
    raise SystemExit(0 if report['passed'] else 1)
