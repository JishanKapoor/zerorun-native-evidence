"""One normal-imported native parent call; its native Process target is retained."""


def read_case(argument):
    """Large native inputs travel through a pinned file, never a pipe payload."""
    import hashlib
    import json
    from pathlib import Path
    from zerorun_harness.api import canonical
    from zerorun_harness._telemetry_protocol import UnsupportedTransport
    if 'case' in argument:
        return argument['case']
    path=Path(argument['case_path'])
    if path.stat().st_size > 8*1024*1024:
        raise UnsupportedTransport('Native case file exceeds 8 MiB')
    raw=path.read_bytes()
    if len(raw)>8*1024*1024 or hashlib.sha256(raw).hexdigest()!=argument['case_sha256']:
        raise UnsupportedTransport('Native case file identity/size mismatch')
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:
                raise ValueError('Duplicate native case field')
            result[key]=value
        return result
    try:
        case=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        canonical(case)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise UnsupportedTransport('Invalid finite native case JSON') from exc
    fields={'id','code','inputs','expected','entry','atol','fast'}
    if (type(case) is not dict or not fields<=set(case) or set(case)-fields-{'preflight_error'}
        or any(type(case[key]) is not str for key in ('id','code','entry'))
        or type(case['inputs']) is not list or type(case['expected']) is not list
        or type(case['fast']) is not bool or not (type(case['atol']) is int or type(case['atol']) is float)
        or len(case['inputs'])!=len(case['expected'])):
        raise UnsupportedTransport('Native case shape is unsupported')
    return case


def native_budget(profile,binding,case,run_id,max_trace_bytes):
    """Conservative wire/event bounds for this finite original native profile."""
    from zerorun_harness._telemetry_protocol import encode, MAX_FRAME, VERSION, UnsupportedTransport, PrimitiveError
    count=len(case['inputs'])
    if not 1<=count<=4096 or 6*count+6>16384:
        raise UnsupportedTransport('Native inventory/event budget exceeded')
    sizes={'parent':[],'worker':[]}
    pid,seq=2147483647,16384
    identity=dict(run=run_id,candidate=case['id'],obligation=-2147483648,phase='base',attempt=1)
    for name,site in profile['sites'].items():
        values={}
        for field,kind in profile['facts'][site['kind']].items():
            projection=site['projection'][field]
            if 'literal' in projection:
                values[field]=projection['literal']
            elif kind=='int':
                values[field]=-2147483648
            elif kind=='bool':
                values[field]=False
            elif name=='parent-return' and field=='raw' and kind=='str':
                values[field]='timeout'
            else:
                raise UnsupportedTransport('Native frame bound needs an explicit finite field domain')
        event=dict(id=str(pid)+':'+str(seq),kind=site['kind'],site=name,identity=identity,
                   values=values,producer=pid,seq=seq,source_sha256='0'*64,binding_sha256=binding['sha256'])
        try:
            sizes[site['producer_role']].append(len(encode(dict(protocol=VERSION,producer=pid,type='event',seq=seq,event=event))))
        except PrimitiveError as exc:
            raise UnsupportedTransport('Native metadata exceeds a bounded frame') from exc
    limits={'worker':(4*count+2)*max(sizes['worker'])+3*MAX_FRAME,
            'parent':(2*count+4)*max(sizes['parent'])+6*MAX_FRAME}
    if any(value>max_trace_bytes//2 for value in limits.values()):
        raise UnsupportedTransport('Native conservative trace byte budget exceeded')
    return dict(inputs=count,semantic_events_upper=6*count+6,wire_bytes_upper=limits,
                max_trace_bytes=max_trace_bytes,scope='Finite native profile preflight; channel loss still invalidates acquisition')


def run(session, argument):
    import hashlib
    import importlib
    import json
    from pathlib import Path
    import sys
    from zerorun_harness.binding import recorder, validate_binding
    from zerorun_harness.lifecycle_binding import validate_lifecycle_binding

    prepared = Path(argument["prepared"])
    case = read_case(argument)
    p = json.loads((prepared / "profile.json").read_text())
    binding = json.loads((prepared / "binding.json").read_text())
    envelope = json.loads((prepared / "lifecycle.json").read_text())
    validate_binding(p, binding)
    validate_lifecycle_binding(binding, envelope)
    native_budget(p,binding,case,argument['run'],session.max_trace_bytes)
    root = prepared / "observed"
    inventory = json.loads((prepared / "observed-files.json").read_text())
    for name, expected in inventory.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Observed source dependency changed: " + name)
    context = dict(run=argument["run"], candidate=case["id"], phase="base", attempt=1)
    session.install_observer(
        lambda emitter, pid: recorder(p, binding, emitter, pid, context=context),
        child_start_site="native-child-started", process_local="p",
        buffer_locals=("details", "progress", "stat"),
    )
    sys.path.insert(0, str(root))
    native = importlib.import_module("evalplus.eval")
    if Path(native.__file__).resolve() != (root / "evalplus/eval/__init__.py").resolve():
        raise ValueError("Native module did not originate in sealed package")
    native.__zr_observe = session.observe
    native.__zr_lifecycle = session.lifecycle
    grade, details = native.untrusted_check(
        dataset="humaneval", code=case["code"], inputs=case["inputs"],
        entry_point=case["entry"], expected=case["expected"], atol=case["atol"],
        ref_time=["invalid"] if case.get("preflight_error") else [0.001] * len(case["inputs"]),
        fast_check=case["fast"], min_time_limit=0.08, gt_time_limit_factor=4,
    )
    if 'case_path' in argument:
        # A large native return also exceeds the small control-message grammar.
        # Retain its exact bytes in an explicit fresh acquisition artifact and
        # return only its identity/count through the bounded control plane.
        result={'grade':grade,'details':list(details)}
        raw=json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        target=Path(argument['native_result_path'])
        with target.open('xb') as stream:
            stream.write(raw)
        return dict(grade=grade,details_count=len(details),native_result_path=str(target),
                    native_result_sha256=hashlib.sha256(raw).hexdigest())
    return {"grade": grade, "details": list(details)}
