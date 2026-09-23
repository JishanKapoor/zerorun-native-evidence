"""Freeze original source and authored controls before Inspect native execution."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parents[1]/'src'))
from declarations import PIN,RUN,RESULTS,METRIC,profile,case_definitions,case_inventory,expected_site_identities
from native_driver import source_inventory
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding


def prepare(workspace, output):
    workspace,output=Path(workspace),Path(output)
    output.mkdir(parents=True,exist_ok=False)
    native=workspace/'study_s7/inspect/upstream/src'
    p=profile()
    b=generate_binding(p,{path:(native/path).read_text(encoding='utf-8') for path in [RUN,RESULTS,METRIC]},grammar_version='1.3.0')
    cases=case_definitions()
    hashes=source_inventory(native)
    inventories={c['id']:case_inventory(c,'s8-inspect-'+c['id']) for c in cases}
    witnesses={c['id']:expected_site_identities(c,'s8-inspect-'+c['id']) for c in cases}
    for name,value in [('profile',p),('binding',b),('cases',cases),('source-hashes',hashes),('inventories',inventories),('expected-witnesses',witnesses)]:
        (output/(name+'.json')).write_text(json.dumps(value,indent=2),encoding='utf-8')
    image=workspace/'study_s8/inspect/image-r2'
    image_id=json.loads((image/'dependency-image-identity.stdout.txt').read_text())[0]['Id']
    freeze=dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_revision=PIN,
        scope='Authored original Inspect eval commitments and actual raw/reduced metric consumers; no independent extension or primary cohort',
        dependency_image=dict(image_id=image_id,dependency_report_sha256=hashlib.sha256((image/'dependency-install.json').read_bytes()).hexdigest(),
            native_install_sha256=hashlib.sha256((image/'native-install.json').read_bytes()).hexdigest(),
            environment_freeze_sha256=hashlib.sha256((image/'dependency-freeze.txt').read_bytes()).hexdigest()),
        profile_sha256=digest(p),binding_sha256=b['sha256'],case_sha256=digest(cases),source_inventory_sha256=digest(hashes),
        inventory_sha256=digest(inventories),expected_witnesses_sha256=digest(witnesses),
        logical_views=len(p['sites']),static_source_matches=len(b['sites']),
        distinct_native_statements=len({(r['path'],r['function'],r['line']) for r in b['sites']}),
        distinct_statement_positions=len({(r['path'],r['function'],r['line'],r['position']) for r in b['sites']}),
        stable_native_comparison=['status','samples.sample_id','samples.epoch','samples.input','samples.target','samples.metadata',
            'samples.error_message','samples.scores.native_model_dump_json','results.native_model_dump_json','reductions.native_model_dump_json','model_usage'],
        full_logs_retained=True,excluded_operational_fields=['UUIDs','timestamps','durations','traceback source locations'],
        native_options=dict(score_display=False,display='none',max_samples=1,fail_on_error=False,epochs=2),
        helper_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))},
        core_sha256={p.relative_to(HERE.parents[1]/'src/zerorun_harness').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted((HERE.parents[1]/'src/zerorun_harness').rglob('*'))
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'})
    (output/'freeze.json').write_text(json.dumps(freeze,indent=2),encoding='utf-8')
    return freeze


if __name__=='__main__':print(json.dumps(prepare(sys.argv[1],sys.argv[2]),indent=2))
