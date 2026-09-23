"""Freeze four standalone original-native regression calls; execute none."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent
from zerorun_harness.api import digest
from zerorun_harness.declarative import seal
from zerorun_harness.extensions import export, audit

CASES=[('before','polynomial-accepted-continue'),('after','polynomial-accepted-continue'),
       ('parent-reordered','mixed-dispositions'),('after','external-parent-timeout')]


def load(path):
    return json.loads(path.read_text())


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(prepared,campaign,output):
    output.mkdir(parents=True,exist_ok=False)
    design=[]
    for variant,caseid in CASES:
        name=variant+'-'+caseid
        folder=output/name
        folder.mkdir()
        stage=prepared/variant
        acquired=campaign/variant/caseid
        p,b,q=load(stage/'profile.json'),load(stage/'binding.json'),load(campaign/variant/'qualification.json')
        c,h=load(acquired/'case.json'),load(acquired/'health.json')
        events=load(acquired/'batch-acquisition.json')['events']
        bundle=seal(dict(schema='zerorun-extension-capture/1',mode='saved-qualified-relationships',
            extension=dict(id=p['id'],version=p['version'],sha256=digest(p)),policy=p,binding=b,case=c,
            observations=events,health=h,qualification=q,components={
                'engine':'1.0.0','policy':dict(id=p['id'],version=p['version'],sha256=digest(p)),
                'binding':dict(version=b['grammar_version'],sha256=b['sha256']),
                'export':{'version':'1.0.0'},'case':dict(version=c['version'],sha256=digest(c))}))
        assert audit(bundle)==load(acquired/'audit.json')
        save(folder/'bundle.json',bundle)
        save(folder/'expected-primary.json',audit(bundle))
        shutil.copytree(stage/'original',folder/'source')
        source=folder/'source'
        for filename in ('reference.py','native_recipe.py'):
            shutil.copyfile(HERE/filename,source/filename)
        nativecase=load(acquired/'native-case.json')
        recipe=dict(schema='zerorun-extension-native-recipe/2',
                    source_files={path.relative_to(source).as_posix():sha(path) for path in sorted(source.rglob('*')) if path.is_file()},
                    module='native_recipe',function='observe',args=[nativecase,variant+':'+caseid],
                    kwargs={'evidence_directory':'native-reference','native_sources':load(stage/'original-files.json')},reference_origin_sha256=sha(source/'reference.py'),
                    justification='One original native untrusted_check call with original actual child; independent raw opcode/state journal and per-rule native completion; exposed development control')
        save(folder/'recipe.json',recipe)
        (folder/'regression.py').write_text(export(bundle,mode='native-regression',recipe=recipe),encoding='utf-8')
        design.append(dict(id=name,variant=variant,case=caseid,expected_native_bank_calls=1,
                           expected_assertion_count=len(audit(bundle)['records'])))
    shutil.copyfile(Path(__file__).with_name('export_campaign.py'),output/'campaign.py')
    files={path.relative_to(output).as_posix():sha(path) for path in sorted(output.rglob('*')) if path.is_file()}
    manifest=dict(schema='s8-evalplus-standalone-export-design/1',cases=design,files=files,
                  expected_native_bank_calls=4,source_preparation_sha256=sha(prepared/'design.json'),
                  scope='Four exposed native regression demonstrations; no framework imports at runtime, independent investigator or study cohort credit')
    save(output/'design.json',manifest)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepared',type=Path,required=True)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run(args.prepared,args.campaign,args.output)
    print(json.dumps({'cases':report['cases'],'native_bank_calls':report['expected_native_bank_calls']},indent=2))
