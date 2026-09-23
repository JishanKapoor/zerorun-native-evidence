"""Freeze new real pytest execution controls and reusable original SWE bindings."""
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]/'src'))
sys.path.insert(0,str(HERE.parent))
from pytest_native import declarations as py_decl
from pytest_native.fixtures import TEST_SOURCE,EXPECTED
from pytest_native.native import source_inventory
from swe_joined.declarations import REVISIONS,case_inventory
from zerorun_harness.api import digest
from zerorun_harness.binding import generate_binding,validate_binding


def write(path,value):path.write_text(json.dumps(value,indent=2),encoding='utf-8')
def prepare(workspace,output):
    workspace,output=Path(workspace),Path(output);output.mkdir(parents=True,exist_ok=False)
    p=py_decl.profile();root=Path(importlib.util.find_spec('_pytest').origin).parent
    sources={path:(root/Path(path).name).read_text(encoding='utf-8') for path in [py_decl.RUNNER,py_decl.REPORTS,py_decl.TERMINAL]}
    b=generate_binding(p,sources,grammar_version='1.4.0');py_source=source_inventory()
    cases=[dict(id='before-attempt1',version='before',attempt=1),dict(id='after-attempt2',version='after',attempt=2),
           dict(id='no-native-call',version='after',attempt=1,no_call=True)]
    for name,value in [('pytest-profile',p),('pytest-binding',b),('pytest-source',py_source),('cases',cases),('expected-phases',EXPECTED)]:write(output/(name+'.json'),value)
    (output/'test_native_controls.py').write_text(TEST_SOURCE,encoding='utf-8',newline='\n')
    inventories={}
    for version in REVISIONS:
        previous=workspace/'study_s8/swe_joined/fixtures-r3'/version
        sp=json.loads((previous/'profile.json').read_text());sb=json.loads((previous/'binding.json').read_text());validate_binding(sp,sb)
        target=output/version;target.mkdir()
        for name,value in [('swe-profile',sp),('swe-binding',sb),('swe-source',json.loads((previous/'source-hashes.json').read_text())),
                           ('swe-prior-qualification',json.loads((workspace/'study_s8/swe_joined/source-r3/campaign'/(version+'-qualification.json')).read_text()))]:write(target/(name+'.json'),value)
    for case in cases:
        run='s8-pytest-'+case['id']
        if case.get('no_call'):inventories[case['id']]=dict(pytest=[],swe=[]);continue
        swe_case=dict(id=case['id'],instances=[dict(id='a',log='SKIPPED [1]',fail_to_pass=['test_native_controls.py::test_pass'],pass_to_pass=['test_native_controls.py::test_parameter[one]'])])
        si=case_inventory(swe_case,run)
        for name in EXPECTED:
            ident=dict(run=run,candidate='authored-joined',instance='a',phase='native-parser',obligation='test_native_controls.py::'+name,attempt=1)
            if ident not in si:si.append(ident)
        inventories[case['id']]=dict(pytest=py_decl.case_inventory(EXPECTED,run,case['attempt']),swe=si)
    write(output/'inventories.json',inventories)
    # Authored teardown-error emits call PASSED then teardown ERROR; the
    # dual-error fixture emits setup ERROR then teardown ERROR. The native
    # parser deliberately has no phase field in its node-keyed map/loop identity.
    expected_ambiguities={case['id']:([
        dict(relationship=rule,obligation='test_native_controls.py::'+node)
        for node in ['test_teardown_error','test_two_phase_errors']
        for rule in ['parser-required-store','parser-status-preserved']]
        if not case.get('no_call') else []) for case in cases}
    write(output/'expected-ambiguities.json',expected_ambiguities)
    image=json.loads((workspace/'study_s8/swe/image-r1/dependency-image-identity.stdout.txt').read_text())[0]['Id']
    files={p.relative_to(HERE.parents[1]).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for base in [HERE,HERE.parent/'swe_joined',HERE.parent/'pytest_native',HERE.parents[1]/'src/zerorun_harness']
           for p in sorted(base.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    freeze=dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),image_id=image,source_files=files,
        pytest_source_sha256=digest(py_source),pytest_profile_sha256=digest(p),pytest_binding_sha256=b['sha256'],
        cases_sha256=digest(cases),inventories_sha256=digest(inventories),source_revisions=REVISIONS,
        expected_ambiguities_sha256=digest(expected_ambiguities),
        actual_pytest_nodes=10,actual_reports_per_execution=28,planned_pytest_api_calls=4,planned_swe_api_calls=8,
        scope='Real authored pytest phase execution and original SWE saved-log pipeline in one capture; two acquisition attempts, no upstream retry or benchmark patch claim',
        comparison='Actual native phase reports and SWE returns/report JSON bytes; raw timed terminal streams retained separately')
    write(output/'freeze.json',freeze);return freeze


if __name__=='__main__':print(json.dumps(prepare(sys.argv[1],sys.argv[2]),indent=2))
