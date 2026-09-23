"""Two qualified domain profiles share one actual native capture/emitter."""
import hashlib
import json
import os
from pathlib import Path
import sys


def run(emitter,options):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from swe_pytest.driver import execute_pytest,write_json,stable_swe
    from pytest_native.native import load_native as load_pytest
    from swe_joined.native_driver import load_native as load_swe,run_case
    from zerorun_harness.binding import recorder
    from zerorun_harness.records import register_records
    from zerorun_harness.projection import project
    fixtures=Path(options['fixture_root']);case=options['case'];output=Path(options['route_output']);output.mkdir()
    p=json.loads((fixtures/'pytest-profile.json').read_text());b=json.loads((fixtures/'pytest-binding.json').read_text())
    box={}
    def observe(site,values):
        result=box['callback'](site,values)
        if result is False:
            errors={}
            for field,spec in p['sites'][site]['projection'].items():
                try:project(spec,values,box['context'],records=box['registry'])
                except Exception as error:errors[field]=dict(type=type(error).__name__,message=str(error))
            with (output/'projection-rejections.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(dict(site=site,errors=errors))+'\n')
        return result
    pytest,_=load_pytest(json.loads((fixtures/'pytest-source.json').read_text()),b['transformed'],observe)
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter
    class RegisterAfterNativeConfiguration:
        def pytest_sessionstart(self,session):
            # Stock legacypath legitimately installs TerminalReporter.startdir
            # during native configuration. Freeze runtime class shape after
            # that original setup and before any selected report boundary.
            if 'callback' in box:raise ValueError('Native session registered twice')
            registry=register_records(p,b,{'report':TestReport,'terminal':TerminalReporter})
            box.update(registry=registry,context=dict(run=options['run'],candidate='authored-pytest',attempt=case['attempt']))
            box['callback']=recorder(p,b,emitter,os.getpid(),records=registry,context=box['context'])
    folder=fixtures/case['version'];sp=json.loads((folder/'swe-profile.json').read_text());sb=json.loads((folder/'swe-binding.json').read_text())
    swe_callback=recorder(sp,sb,emitter,os.getpid(),context=dict(run=options['run'],candidate='authored-joined',instance='a'))
    native=load_swe(options['native_root'],json.loads((folder/'swe-source.json').read_text()),sb['transformed'],swe_callback)
    if case.get('no_call'):
        result=dict(pytest=None,swe=None,stable_swe=None)
    else:
        pytest_result,swe_case=execute_pytest(pytest,case,options['run'],options['work']+'/pytest',output,
            acquisition_plugins=[RegisterAfterNativeConfiguration()])
        swe_result=run_case(native,swe_case,options['run'],options['work']+'/swe',output/'swe-calls.jsonl')
        result=dict(pytest=pytest_result,swe=swe_result,stable_swe=stable_swe(swe_result))
    path=output/'native.json';write_json(path,result)
    return dict(output_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
