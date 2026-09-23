def run(mode):
    import hashlib, sys
    from pathlib import Path
    sys.path.insert(0, '/native_evalplus')
    import evalplus.eval as native
    if hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() != '3c833c39b842e33f251c83db4347e0a95191909f23b390c12d73ab29a28a4daf':
        raise ValueError('Native EvalPlus source identity mismatch')
    run, candidate, phase, attempt = 'native-api-control', mode, 'base', 1
    obligation = 0
    code = 'def check(x): return x' if mode in ('pass', 'fast-reject') else 'def check(x): return not x'
    expected = [True, False] if mode != 'fast-reject' else [False, False]
    grade, details = native.untrusted_check('humaneval', code, [[True], [False]], 'check', expected, 0,
                                           [0.01, 0.01], fast_check=(mode == 'fast-reject'), min_time_limit=0.2)
    inventory = [dict(run=run,candidate=candidate,obligation=i,phase=phase,attempt=attempt) for i in range(2)]
    facts = []
    for obligation, value in enumerate(details):
        raw = int(value)
        facts.append(dict(kind='detail', identity=inventory[obligation], values={'raw':raw}))
    raw_grade = grade
    facts.append(dict(kind='grade', identity=inventory[obligation], values={'raw':raw_grade}))
    return dict(inventory=inventory, facts=facts, native_complete=True)
