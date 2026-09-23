"""Standalone v2 runs pinned native code in an isolated interpreter, without ZeroRun."""

import copy
import hashlib
import json
from importlib.resources import files
import subprocess
import sys

import pytest

from zerorun_harness.api import InvalidEvidence, digest
from zerorun_harness.batches import extract_batches
from zerorun_harness.binding import generate_binding, recorder
from zerorun_harness.extension_exports import native_script
from zerorun_harness import extensions
from zerorun_harness.qualification import qualify
from test_native_projection import one_site
from declarative_support import profile as legacy_profile


SOURCE = """def outer(details, expected=2, status='success', corrupt=False):
    native = details[:]
    accepted = len(native) == expected and all(native)
    grade = not accepted if corrupt else accepted
    terminal = status
    completed = True
    return native, grade, terminal, completed
"""

NATIVE_API = """from native import outer

def run(values, status='success', corrupt=False, damage=None):
    native, grade, terminal, completed = outer(values, 2, status, corrupt)
    def identity(i):
        return dict(run='r', candidate='c', obligation=i, phase='b', attempt=1)
    facts = [dict(kind='raw', identity=identity(i), values={'flag': value}) for i, value in enumerate(native)]
    facts.append(dict(kind='grade', identity=identity(0), values={'accepted': grade}))
    facts.append(dict(kind='finish', identity=identity(0), values={'status': terminal}))
    batch = dict(site='return', identity=dict(run='r', candidate='c', phase='b', attempt=1),
                 size=len(native), fact_indices=list(range(len(native))), complete=completed)
    result = dict(inventory=[identity(0), identity(1)], facts=facts,
                  native_complete={'native-grade': completed}, native_batches=[batch])
    if damage == 'incomplete-batch': batch['complete'] = False
    elif damage == 'lost-index':
        batch['fact_indices'].pop()
        batch['complete'] = False
    elif damage == 'duplicate-index': batch['fact_indices'] = [0, 0]
    elif damage == 'wrong-group': batch['identity']['candidate'] = 'other'
    elif damage == 'dropped-fact': facts.pop(0)
    elif damage == 'dropped-target': facts.pop(-2)
    elif damage == 'dropped-guard': facts.pop()
    elif damage == 'duplicate-guard': facts.append(dict(facts[-1]))
    elif damage == 'missing-batch': result['native_batches'] = []
    elif damage == 'completion-false': result['native_complete']['native-grade'] = False
    elif damage == 'completion-malformed': result['native_complete'] = True
    elif damage == 'completion-missing': result['native_complete'] = {}
    elif damage == 'inventory-changed': result['inventory'][0]['candidate'] = 'other'
    return result
"""


def native_profile():
    p = one_site("outer", "native = details[:]", "after", {"item": True})
    p["id"] = "authored-standalone-v2"
    site = p["sites"]["return"]
    site.update(batch={"local": "native", "max_items": 64})
    site["projection"]["obligation"] = {"ordinal": True}
    for name, kind, anchor, field, projection in [
        (
            "grade",
            "grade",
            "grade = not accepted if corrupt else accepted",
            "accepted",
            {"local": "grade"},
        ),
        ("terminal", "finish", "terminal = status", "status", {"local": "terminal"}),
    ]:
        new = copy.deepcopy(site)
        del new["batch"]
        new.update(kind=kind, anchor=anchor)
        new["projection"].pop("flag")
        new["projection"]["obligation"] = {"literal": 0}
        new["projection"][field] = projection
        p["sites"][name] = new
    p["facts"].update(grade={"accepted": "bool"}, finish={"status": "str"})
    p["rules"][0].update(
        id="native-grade",
        check="C3",
        consumer="grade",
        keys=[key for key in p["identity"] if key != "obligation"],
        target_field="accepted",
        operator="all_in",
        statuses=[1],
        requires=["return", "grade", "terminal"],
        inventory_policy="complete_batch_membership",
        guard={"kind": "finish", "field": "status", "in": ["success"]},
    )
    return p


@pytest.fixture
def native_bundle(monkeypatch):
    p = native_profile()
    binding = generate_binding(p, {"native.py": SOURCE})
    raw = []

    class Sink:
        def emit(self, event):
            raw.append(copy.deepcopy(event))
            return True

    scope = {"__zr_observe": recorder(p, binding, Sink(), 321)}
    exec(compile(binding["transformed"]["native.py"], "native.py", "exec"), scope)
    assert scope["outer"]([1, 1]) == ([1, 1], True, "success", True)
    events = extract_batches(p, binding, raw)["events"]

    def identity(i):
        return dict(run="r", candidate="c", obligation=i, phase="b", attempt=1)

    # Literal reference for this fixed authored input; not derived from monitor verdicts.
    expected = {
        "return": [
            dict(identity=identity(0), values={"flag": 1}),
            dict(identity=identity(1), values={"flag": 1}),
        ],
        "grade": [dict(identity=identity(0), values={"accepted": True})],
        "terminal": [dict(identity=identity(0), values={"status": "success"})],
    }
    controls = [
        dict(
            id=site + "-authored-positive",
            site=site,
            role="positive",
            reference=dict(
                source_sha256=hashlib.sha256(NATIVE_API.encode()).hexdigest(),
                recipe_sha256=digest({"authored_input": [1, 1], "expected": expected}),
                native_source_sha256=digest(binding["original_sources"]),
                output_sha256=digest(facts),
                framework_semantics_imported=False,
                facts=facts,
            ),
            observed=[event for event in events if event["site"] == site],
        )
        for site, facts in expected.items()
    ]
    qualification = qualify(p, binding, controls)
    assert all(qualification["sites"].values())
    manifest = dict(
        schema="zerorun-extension-manifest/1",
        extension=dict(id=p["id"], version=p["version"], sha256=digest(p)),
        binding=binding,
        qualification=qualification,
        case=dict(
            id="authored-native-export-v2",
            version="1",
            inventory=[identity(0), identity(1)],
            source_sha256=digest(binding["original_sources"]),
            input_sha256=digest([1, 1]),
        ),
        observations=events,
        health=dict(
            binding_sha256=binding["sha256"],
            sites=qualification["sites"],
            qualification_sha256=qualification["sha256"],
            native_complete={"native-grade": True},
            transport={"321": True},
            batch_journal=raw,
        ),
    )
    monkeypatch.setattr(extensions, "load_extension", lambda selection: p)
    return extensions.capture(manifest)


def recipe(bundle, kwargs, version=2):
    return dict(
        schema="zerorun-extension-native-recipe/" + str(version),
        source_files={
            **bundle["binding"]["original_sources"],
            "native_api.py": hashlib.sha256(NATIVE_API.encode()).hexdigest(),
        },
        module="native_api",
        function="run",
        args=[],
        kwargs=kwargs,
        reference_origin_sha256=hashlib.sha256(NATIVE_API.encode()).hexdigest(),
        justification="Authored native API with explicit final-stage marker and raw collection population",
    )


def run_isolated(tmp_path, bundle, kwargs):
    native = tmp_path / "native"
    native.mkdir()
    (native / "native.py").write_bytes(SOURCE.encode())
    (native / "native_api.py").write_bytes(NATIVE_API.encode())
    script = tmp_path / "regression.py"
    script.write_text(native_script(bundle, recipe(bundle, kwargs)), encoding="utf-8")
    output = tmp_path / "result.json"
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=15,
    )
    receipt = json.loads(output.read_text())
    assert receipt["schema"] == "zerorun-standalone-result/2"
    assert receipt["classification_dependency"] is False
    assert receipt["native_calls"] == 1
    assert receipt["native_call_unit"] == "recipe_invocation_attempt"
    assert (
        receipt["result"]
        == {0: "PASS", 1: "FAIL", 2: "UNASSESSABLE"}[process.returncode]
    )
    return receipt, script, native, output


@pytest.mark.parametrize("values", [[], [1], [1, 1], [0], [1, 0]])
@pytest.mark.parametrize("corrupt", [False, True])
def test_v2_isolated_native_empty_short_and_full_populations(
    native_bundle, tmp_path, values, corrupt
):
    receipt, *_ = run_isolated(
        tmp_path, native_bundle, dict(values=values, corrupt=corrupt)
    )
    assert receipt["result"] == ("FAIL" if corrupt else "PASS")


def test_v2_false_status_guard_is_observed_and_explicit(native_bundle, tmp_path):
    receipt, *_ = run_isolated(
        tmp_path, native_bundle, dict(values=[1], corrupt=True, status="skipped")
    )
    assert receipt["result"] == "PASS"
    assert receipt["assertions"][0]["reason"] == "native_rule_guard_not_applicable"
    assert receipt["native"]["facts"][-1]["values"] == {"status": "skipped"}


@pytest.mark.parametrize(
    "damage",
    [
        "incomplete-batch",
        "lost-index",
        "missing-batch",
        "completion-false",
        "dropped-target",
        "dropped-guard",
        "duplicate-guard",
    ],
)
def test_v2_missing_raw_premises_cannot_close_short_all_true_population(
    native_bundle, tmp_path, damage
):
    receipt, *_ = run_isolated(tmp_path, native_bundle, dict(values=[1], damage=damage))
    assert receipt["result"] == "UNASSESSABLE"


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate-index",
        "wrong-group",
        "dropped-fact",
        "completion-malformed",
        "completion-missing",
        "inventory-changed",
    ],
)
def test_v2_malformed_populations_or_completion_refuse(native_bundle, tmp_path, damage):
    receipt, *_ = run_isolated(tmp_path, native_bundle, dict(values=[1], damage=damage))
    assert receipt["result"] == "UNASSESSABLE"
    assert receipt["exception"] == "ValueError"


def test_v2_incomplete_batch_does_not_erase_witnessed_false_operand(
    native_bundle, tmp_path
):
    receipt, *_ = run_isolated(
        tmp_path,
        native_bundle,
        dict(values=[0], corrupt=True, damage="incomplete-batch"),
    )
    assert receipt["result"] == "FAIL"


def test_v2_exclusive_output_precedes_native_action(native_bundle, tmp_path):
    receipt, script, native, output = run_isolated(
        tmp_path, native_bundle, dict(values=[1, 1])
    )
    previous = output.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0 and output.read_bytes() == previous
    assert receipt["result"] == "PASS"


def test_new_native_semantics_cannot_use_v1_reference_shape(native_bundle):
    with pytest.raises(InvalidEvidence, match="version 2"):
        native_script(
            native_bundle, recipe(native_bundle, dict(values=[1, 1]), version=1)
        )


def test_v1_resource_and_actual_writer_output_are_byte_identical(monkeypatch):
    template = (
        files("zerorun_harness")
        .joinpath("resources/extension_native_template.txt")
        .read_bytes()
    )
    assert (
        hashlib.sha256(template).hexdigest()
        == "538b26d2b3646716b3dc3f96fc598f85e2fff0e4e756d32bfb8514b190133e19"
    )
    monkeypatch.setattr(extensions, "audit", lambda bundle: None)
    bundle = dict(
        policy=legacy_profile(),
        binding=dict(original_sources={"native.py": "a" * 64}, sha256="b" * 64),
        case={
            "inventory": [
                dict(run="r", candidate="c", obligation=0, phase="base", attempt=1)
            ]
        },
        qualification={"sha256": "c" * 64},
    )
    old_recipe = dict(
        schema="zerorun-extension-native-recipe/1",
        source_files={"native.py": "a" * 64, "native_api.py": "d" * 64},
        module="native_api",
        function="run",
        args=[],
        kwargs={},
        reference_origin_sha256="e" * 64,
        justification="Fixed byte-compatibility writer fixture",
    )
    # This hash was measured before the v2 implementation from the saved v1 writer.
    assert (
        hashlib.sha256(native_script(bundle, old_recipe).encode()).hexdigest()
        == "76c728e8a18477fb13c4278156464f3e9fe6f26fff192f1cee276af8c6290b51"
    )


def test_v2_output_does_not_copy_classifier_results(native_bundle, monkeypatch):
    configured = recipe(native_bundle, dict(values=[1, 1]))
    expected = native_script(native_bundle, configured)
    monkeypatch.setattr(
        extensions,
        "audit",
        lambda bundle: {"records": [{"status": "CORRUPTED_CLASSIFIER"}]},
    )
    assert native_script(native_bundle, configured) == expected
    assert "CORRUPTED_CLASSIFIER" not in expected


def direct_native_result(values=(1, 1)):
    scope = {}
    exec(SOURCE, scope)
    exec(NATIVE_API.replace("from native import outer\n", ""), scope)
    return scope["run"](list(values))


def standalone_checker():
    template = (
        files("zerorun_harness")
        .joinpath("resources/extension_native_template_v2.txt")
        .read_text()
    )
    scope = {"__name__": "independent_standalone_checker_test"}
    exec(
        template.replace("__PAYLOAD_JSON__", repr("{}")).replace(
            "__PAYLOAD_SHA__", "0" * 64
        ),
        scope,
    )
    return scope["verify_native"]


def stored_population(values=(1, 1), *, reverse=False):
    """Raw reference-format fixture: scientific names differ from positions."""
    profile = native_profile()
    profile["identity"]["sample_id"] = "str"
    profile["record_types"] = {"score": dict(module="native_model", name="Score",
        path="native_model.py", fields=["sample_id", "value"])}
    producer = profile["sites"]["return"]
    producer["batch"]["ordinal"] = "acquisition"
    producer["projection"]["obligation"] = {"literal": 0}
    producer["projection"]["sample_id"] = {"item": True, "path": [{"stored": "sample_id", "record": "score"}]}
    producer["projection"]["flag"] = {"item": True, "path": [{"stored": "value", "record": "score"}]}
    for name in ("grade", "terminal"):
        profile["sites"][name]["projection"]["sample_id"] = {"literal": "alpha"}
    profile["rules"][0]["keys"] = [key for key in profile["identity"] if key != "sample_id"]
    from zerorun_harness.declarative import validate_profile
    validate_profile(profile)
    def identity(name):
        return dict(run="r", candidate="c", obligation=0, phase="b", attempt=1, sample_id=name)
    names = ["alpha", "beta"][:len(values)]
    pairs = list(zip(names, values))
    if reverse:
        pairs.reverse()
    facts = [dict(kind="raw", identity=identity(name), values={"flag": value}) for name, value in pairs]
    facts += [dict(kind="grade", identity=identity("alpha"), values={"accepted": len(values) == 2 and all(values)}),
              dict(kind="finish", identity=identity("alpha"), values={"status": "success"})]
    batch = dict(site="return", identity={key: value for key, value in identity("alpha").items() if key != "sample_id"},
                 size=len(values), fact_indices=list(range(len(values))), ordinals=list(range(len(values))), complete=True)
    native = dict(inventory=[identity("alpha"), identity("beta")], facts=facts,
                  native_complete={"native-grade": True}, native_batches=[batch])
    return profile, native


@pytest.mark.parametrize("values,reverse", [([], False), ([1], False), ([1, 1], False), ([1, 0], True)])
def test_v2_acquisition_positions_do_not_replace_actual_stored_sample_identity(values, reverse):
    profile, native = stored_population(values, reverse=reverse)
    rows = standalone_checker()(profile, native, native["inventory"])
    assert len(rows) == 1 and rows[0]["result"] == "PASS"


@pytest.mark.parametrize("damage", ["missing", "bool", "negative", "oversize", "duplicate", "reverse", "short", "mapping", "identity-field"])
def test_v2_acquisition_mode_requires_exact_explicit_native_ordinals(damage):
    profile, native = stored_population()
    batch = native["native_batches"][0]
    if damage == "missing":
        del batch["ordinals"]
    elif damage == "bool":
        batch["ordinals"][0] = False
    elif damage == "negative":
        batch["ordinals"][0] = -1
    elif damage == "oversize":
        batch["ordinals"][1] = 2
    elif damage == "duplicate":
        batch["ordinals"][1] = 0
    elif damage == "reverse":
        batch["ordinals"].reverse()
    elif damage == "short":
        batch["ordinals"].pop()
    elif damage == "mapping":
        batch["ordinals"] = {"0": 0, "1": 1}
    else:
        batch["identity"]["sample_id"] = "alpha"
    with pytest.raises(ValueError):
        standalone_checker()(profile, native, native["inventory"])


def test_v2_acquisition_lost_element_cannot_certify_short_population():
    profile, native = stored_population([1])
    batch = native["native_batches"][0]
    batch.update(complete=False, size=2)
    assert standalone_checker()(profile, native, native["inventory"])[0]["result"] == "UNASSESSABLE"


def test_v2_legacy_batch_mode_refuses_new_acquisition_ordinal_field():
    native = direct_native_result()
    native["native_batches"][0]["ordinals"] = [0, 1]
    with pytest.raises(ValueError):
        standalone_checker()(native_profile(), native, native["inventory"])


RECORD_SOURCE = '''from native_model import Score

def outer(scores, mode):
    committed = scores[:]
    if mode == 'empty':
        returned = []
    elif mode == 'short':
        returned = committed[:1]
    elif mode == 'reverse':
        returned = committed[::-1]
    elif mode == 'duplicate':
        returned = [committed[0], committed[0]]
    elif mode == 'corrupt':
        returned = [Score(score.sample_id, 1-score.value) for score in committed]
    else:
        returned = committed[:]
    native = returned
    completed = True
    return committed, native, completed
'''

RECORD_API = '''from native import outer
from native_model import Score

def run(mode):
    committed, native, completed = outer([Score('alpha', 1), Score('beta', 0)], mode)
    def identity(name):
        return dict(run='r', candidate='c', obligation=0, phase='b', attempt=1, sample_id=name)
    facts, batches = [], []
    for site, kind, values in [('commit', 'raw', committed), ('return', 'consumer', native)]:
        indices, ordinals = [], []
        for ordinal, value in enumerate(values):
            indices.append(len(facts));ordinals.append(ordinal)
            facts.append(dict(kind=kind, identity=identity(value.sample_id), values={'flag': value.value}))
        batches.append(dict(site=site, identity=dict(run='r',candidate='c',obligation=0,phase='b',attempt=1),
                            size=len(values), fact_indices=indices, ordinals=ordinals, complete=completed))
    return dict(inventory=[identity('alpha'),identity('beta')], facts=facts,
                native_complete={'native-record-preserved':completed}, native_batches=batches)
'''


@pytest.fixture
def stored_record_native_bundle(monkeypatch):
    from types import ModuleType
    from zerorun_harness.records import register_records
    from test_record_batches import MODEL, setup_profile
    profile = setup_profile()
    profile['id'] = 'authored-stored-native-export'
    consumer = profile['sites']['return']
    consumer.update(anchor='native = returned', kind='consumer')
    producer = copy.deepcopy(consumer)
    producer.update(anchor='committed = scores[:]', kind='raw')
    producer['batch']['local'] = 'committed'
    profile['sites']['commit'] = producer
    profile['facts']['consumer'] = {'flag':'int'}
    rule = profile['rules'][0]
    rule.update(id='native-record-preserved', check='C2', consumer='consumer', source_field='flag',
                target_field='flag', operator='identity', requires=['commit','return'])
    binding = generate_binding(profile, {'native.py': RECORD_SOURCE, 'native_model.py': MODEL}, grammar_version='1.3.0')
    module = ModuleType('native_model')
    exec(MODEL, module.__dict__)
    monkeypatch.setitem(sys.modules, 'native_model', module)
    registry = register_records(profile, binding, {'score':module.Score})
    raw = []
    class Sink:
        def emit(self, event):
            raw.append(copy.deepcopy(event))
            return True
    scope = {'__zr_observe':recorder(profile, binding, Sink(), 321, records=registry)}
    exec(binding['transformed']['native.py'], scope)
    scope['outer']([module.Score('alpha',1),module.Score('beta',0)], 'normal')
    events = extract_batches(profile, binding, raw)['events']
    def identity(name):
        return dict(run='r',candidate='c',obligation=0,phase='b',attempt=1,sample_id=name)
    # Literal independent reference for the fixed native qualification input.
    expected = [dict(identity=identity('alpha'),values={'flag':1}),
                dict(identity=identity('beta'),values={'flag':0})]
    controls = [dict(id=site+'-positive',site=site,role='positive', reference=dict(
        source_sha256=hashlib.sha256(RECORD_API.encode()).hexdigest(),
        recipe_sha256=digest({'mode':'normal','expected':expected}),
        native_source_sha256=digest(binding['original_sources']), output_sha256=digest(expected),
        framework_semantics_imported=False,facts=expected),
        observed=[event for event in events if event['site']==site]) for site in profile['sites']]
    qualification = qualify(profile,binding,controls)
    assert all(qualification['sites'].values())
    manifest = dict(schema='zerorun-extension-manifest/1',
        extension=dict(id=profile['id'],version=profile['version'],sha256=digest(profile)),
        binding=binding,qualification=qualification,
        case=dict(id='authored-stored-native-export',version='1',inventory=[identity('alpha'),identity('beta')],
                  source_sha256=digest(binding['original_sources']),input_sha256=digest(['alpha','beta'])),
        observations=events,health=dict(binding_sha256=binding['sha256'],sites=qualification['sites'],
            qualification_sha256=qualification['sha256'],native_complete={'native-record-preserved':True},transport={'321':True}))
    monkeypatch.setattr(extensions,'load_extension',lambda selection:profile)
    return extensions.capture(manifest)


@pytest.mark.parametrize('mode,expected', [('normal','PASS'),('reverse','PASS'),('empty','UNASSESSABLE'),
    ('short','UNASSESSABLE'),('duplicate','UNASSESSABLE'),('corrupt','FAIL')])
def test_isolated_v2_runs_original_stored_record_handoff(stored_record_native_bundle,tmp_path,mode,expected):
    from test_record_batches import MODEL
    bundle = stored_record_native_bundle
    configured = dict(schema='zerorun-extension-native-recipe/2',source_files={
        **bundle['binding']['original_sources'],'native_api.py':hashlib.sha256(RECORD_API.encode()).hexdigest()},
        module='native_api',function='run',args=[mode],kwargs={},
        reference_origin_sha256=hashlib.sha256(RECORD_API.encode()).hexdigest(),
        justification='Original authored API returns its actual producer and consumer arrays and completed stage')
    native = tmp_path/'native'
    native.mkdir()
    for name, source in [('native.py',RECORD_SOURCE),('native_model.py',MODEL),('native_api.py',RECORD_API)]:
        (native/name).write_bytes(source.encode())
    script = tmp_path/'regression.py'
    script.write_text(native_script(bundle,configured),encoding='utf-8')
    output = tmp_path/'result.json'
    process = subprocess.run([sys.executable,'-I',str(script),'--source',str(native),'--output',str(output)],
        capture_output=True,text=True,timeout=30)
    result = json.loads(output.read_text())
    assert result['result']==expected, (process.stdout,process.stderr,result)
    assert process.returncode == {'PASS':0,'FAIL':1,'UNASSESSABLE':2}[expected]
    assert result['native_calls']==1 and result['native_call_unit']=='recipe_invocation_attempt'
    assert result['classification_dependency'] is False


def test_v2_completion_is_per_rule_not_a_global_switch():
    profile = native_profile()
    other = copy.deepcopy(profile["rules"][0])
    other["id"] = "separate-native-stage"
    profile["rules"].append(other)
    native = direct_native_result()
    native["native_complete"] = {"native-grade": False, "separate-native-stage": True}
    rows = standalone_checker()(profile, native, native["inventory"])
    assert {row["relationship"]: row["result"] for row in rows} == {
        "native-grade": "UNASSESSABLE",
        "separate-native-stage": "PASS",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "bool-index",
        "outside-index",
        "bool-size",
        "over-cap",
        "false-complete-type",
        "extra-batch-field",
        "extra-completion-rule",
        "extra-result-field",
        "incomplete-missing-members-claim",
    ],
)
def test_v2_batch_schema_cannot_smuggle_completeness(mutation):
    native = direct_native_result()
    batch = native["native_batches"][0]
    if mutation == "bool-index":
        batch["fact_indices"][0] = False
    elif mutation == "outside-index":
        batch["fact_indices"][0] = 99
    elif mutation == "bool-size":
        batch["size"] = True
    elif mutation == "over-cap":
        batch["size"] = 65
    elif mutation == "false-complete-type":
        batch["complete"] = 1
    elif mutation == "extra-batch-field":
        batch["verdict"] = "PASS"
    elif mutation == "extra-completion-rule":
        native["native_complete"]["unknown"] = True
    elif mutation == "extra-result-field":
        native["classified"] = "PASS"
    else:
        batch["fact_indices"].pop()
    with pytest.raises(ValueError):
        standalone_checker()(native_profile(), native, native["inventory"])


def test_v2_empty_batch_cannot_name_a_foreign_case_group():
    native = direct_native_result([])
    native["native_batches"][0]["identity"]["candidate"] = "foreign"
    with pytest.raises(ValueError, match="outside frozen"):
        standalone_checker()(native_profile(), native, native["inventory"])


def test_v2_source_tamper_fails_before_native_call(native_bundle, tmp_path):
    _, script, native, _ = run_isolated(tmp_path, native_bundle, dict(values=[1, 1]))
    (native / "native.py").write_text(SOURCE + "\nchanged = True\n")
    output = tmp_path / "tampered-result.json"
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=15,
    )
    receipt = json.loads(output.read_text())
    assert process.returncode == 2 and receipt["native_calls"] == 0
    assert receipt["result"] == "UNASSESSABLE"


def test_v2_missing_entrypoint_is_not_counted_as_a_native_call(native_bundle, tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    (native / "native.py").write_bytes(SOURCE.encode())
    (native / "native_api.py").write_bytes(NATIVE_API.encode())
    configured = recipe(native_bundle, dict(values=[1, 1]))
    configured["function"] = "absent"
    script = tmp_path / "regression.py"
    script.write_text(native_script(native_bundle, configured), encoding="utf-8")
    output = tmp_path / "result.json"
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=15,
    )
    receipt = json.loads(output.read_text())
    assert process.returncode == 2 and receipt["native_calls"] == 0
    assert receipt["exception"] == "AttributeError"
