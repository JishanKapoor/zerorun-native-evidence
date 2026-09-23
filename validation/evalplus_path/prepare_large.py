"""Freeze finite 128/1000-input authored banks, retaining all prior evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent
from adapter import native_budget


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source,prior,output,dataset_inventory=None):
    output.mkdir(parents=True,exist_ok=False)
    controls=[]
    for revision in ('before','after'):
        shutil.copytree(source/revision,output/revision)
        shutil.copyfile(prior/revision/'qualification.json',output/revision/'prior-qualification.json')
        profile=json.loads((output/revision/'profile.json').read_text())
        binding=json.loads((output/revision/'binding.json').read_text())
        for count in (128,1000):
            case=dict(id='mixed-bank-'+str(count),code='def check(x): return x',inputs=[[i] for i in range(count)],
                      expected=[i if i%2==0 else -1 for i in range(count)],entry='check',atol=0,fast=False)
            filename=revision+'/native-'+str(count)+'.json'
            (output/filename).write_text(json.dumps(case),encoding='utf-8')
            budget=native_budget(profile,binding,case,revision+':'+case['id'],16*1024*1024)
            controls.append(dict(id=revision+'-'+case['id'],revision=revision,case_path=filename,
                                 case_sha256=sha(output/filename),inputs=count,budget=budget,native_bank_calls=2))
    import zerorun_harness
    shutil.copytree(Path(zerorun_harness.__file__).resolve().parent,output/'package/zerorun_harness',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(HERE,output/'implementation',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copyfile(Path(__file__).with_name('large_campaign.py'),output/'campaign.py')
    metadata=dict(scope='No dataset count inventory supplied; authored 128/1000 controls only')
    if dataset_inventory is not None:
        inventory=json.loads(dataset_inventory.read_text())
        metadata=dict(sha256=sha(dataset_inventory),tasks=len(inventory['tasks']),
                      max_base=max(row['base_input_count'] for row in inventory['tasks']),
                      max_plus=max(row['plus_input_count'] for row in inventory['tasks']),
                      max_combined=max(row['base_input_count']+row['plus_input_count'] for row in inventory['tasks']),
                      scope='Supplied count inventory only; each native phase remains a separate bank')
    files={path.relative_to(output).as_posix():sha(path) for path in sorted(output.rglob('*')) if path.is_file()}
    design=dict(schema='s8-evalplus-large-bank-design/1',controls=controls,native_bank_calls=8,files=files,
                retained_dataset_count_review=metadata,scope='Authored finite capacity controls, no scientific cohort or independent-participant credit')
    (output/'design.json').write_text(json.dumps(design,indent=2),encoding='utf-8')
    return design


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--prior',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dataset-count-inventory',type=Path)
    args=parser.parse_args()
    d=run(args.source,args.prior,args.output,args.dataset_count_inventory)
    print(json.dumps({'controls':d['controls'],'dataset':d['retained_dataset_count_review'],'native_bank_calls':8},indent=2))
