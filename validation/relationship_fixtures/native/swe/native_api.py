def run(mode):
    import hashlib, importlib, sys, types
    from pathlib import Path
    for name, rel in [('swebench','swebench'),('swebench.harness','swebench/harness')]:
        if name not in sys.modules:
            package=types.ModuleType(name);package.__path__=[str(Path('/native_swe')/rel)];sys.modules[name]=package
    native=importlib.import_module('swebench.harness.grading')
    if hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() != 'f58def5253794854b9f20de1ac5533555af379fdf731763077c75fa1258b4961':
        raise ValueError('Native SWE source identity mismatch')
    run, candidate, phase, attempt = 'native-api-control', mode, 'grading', 1
    modes={'pass':{'a':'PASSED','b':'PASSED'},'fail':{'a':'FAILED','b':'PASSED'},
           'xfail':{'a':'XFAIL','b':'PASSED'},'maintenance-fail':{'a':'PASSED','b':'FAILED'}}
    report=native.get_eval_tests_report(modes[mode],{'FAIL_TO_PASS':['a'],'PASS_TO_PASS':['b']})
    grade=native.get_resolution_status(report)
    inventory=[dict(run=run,candidate=candidate,obligation='FAIL_TO_PASS:a',phase=phase,attempt=attempt),
               dict(run=run,candidate=candidate,obligation='PASS_TO_PASS:b',phase=phase,attempt=attempt)]
    facts=[]
    for group in ['FAIL_TO_PASS','PASS_TO_PASS']:
        for outcome, tests in report[group].items():
            for test in tests:
                obligation=group+':'+test
                raw = outcome
                identity=dict(run=run,candidate=candidate,obligation=obligation,phase=phase,attempt=attempt)
                facts.append(dict(kind='detail',identity=identity,values={'raw':raw}))
    raw_grade = grade
    facts.append(dict(kind='grade',identity=identity,values={'raw':raw_grade}))
    return dict(inventory=inventory,facts=facts,native_complete=True)
