# SPDX-License-Identifier: MIT
import copy
import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
import pytest

from zerorun_harness import capture, audit, compare, export, report
from zerorun_harness.api import InvalidEvidence
from zerorun_harness.cli import main
from zerorun_harness.declarative import seal, validate_profile
from zerorun_harness.extensions import load_extension
from zerorun_harness.qualification import qualify, validate_qualification
from declarative_support import SOURCE, qualified_manifest


@pytest.fixture
def installed(tmp_path, monkeypatch):
    manifest, profile = qualified_manifest()
    package = tmp_path / "domain"
    package.mkdir()
    (package / "__init__.py").write_text(
        'raise AssertionError("registration must not import executable extension code")'
    )
    (package / "profile.json").write_text(json.dumps(profile))
    entry = SimpleNamespace(
        group="zerorun.extensions.v1", name=profile["id"], value="domain:profile.json"
    )

    def forbidden():
        raise AssertionError("EntryPoint.load() must never execute")

    entry.load = forbidden
    dist = SimpleNamespace(
        metadata={"Name": "zerorun-exposed-domain"},
        version="1.0.0",
        entry_points=[entry],
        files=["domain/profile.json"],
        locate_file=lambda path: tmp_path / path,
    )
    monkeypatch.setattr(
        "zerorun_harness.extensions.metadata.distributions", lambda: [dist]
    )
    return manifest, profile, dist


def test_all_five_public_operations_select_installed_declarations(installed):
    manifest, _, _ = installed
    bundle = capture(manifest)
    assert audit(bundle)["counts"] == {"CONFORMS": 7}
    assert len(compare(bundle, bundle)["records"]) == 7
    assert export(bundle)["native_observations"] == manifest["observations"]
    assert "Binding SHA256:" in report(bundle)
    assert set(bundle["components"]) == {
        "engine",
        "policy",
        "binding",
        "export",
        "case",
    }


def test_five_cli_commands_accept_extension_manifest(installed, tmp_path):
    manifest, _, _ = installed
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    bundle = tmp_path / "capture.json"
    assert main(["capture", str(path), "--output", str(bundle)]) == 0
    for operation in ["audit", "export", "report", "compare"]:
        args = [
            operation,
            str(bundle),
            "--output",
            str(tmp_path / (operation + ".json")),
        ]
        if operation == "compare":
            args.append(str(bundle))
        assert main(args) == 0


def test_missing_callback_disqualifies_actual_site(installed):
    manifest, profile, _ = installed
    controls = copy.deepcopy(manifest["qualification"]["controls"])
    next(c for c in controls if c["id"] == "commit-positive")["observed"] = []
    q = qualify(profile, manifest["binding"], controls)
    assert q["sites"]["commit"] is False and q["sites"]["accept"] is True
    manifest["qualification"] = q
    manifest["health"].update(sites=q["sites"], qualification_sha256=q["sha256"])
    assert audit(capture(manifest))["counts"] == {"INCONCLUSIVE": 7}


@pytest.mark.parametrize(
    "fault", ["identity", "success-path", "reference-import", "forged-site"]
)
def test_qualification_faults_are_not_confident_native_accusations(installed, fault):
    manifest, profile, _ = installed
    controls = copy.deepcopy(manifest["qualification"]["controls"])
    if fault == "identity":
        controls[0]["observed"][0]["identity"]["candidate"] = "incorrect"
        assert (
            qualify(profile, manifest["binding"], controls)["sites"]["accept"] is False
        )
    elif fault == "success-path":
        target = next(c for c in controls if c["id"] == "accept-negative")
        target["observed"] = copy.deepcopy(controls[0]["observed"])
        assert (
            qualify(profile, manifest["binding"], controls)["sites"]["accept"] is False
        )
    elif fault == "reference-import":
        controls[0]["reference"]["framework_semantics_imported"] = True
        with pytest.raises(InvalidEvidence):
            qualify(profile, manifest["binding"], controls)
    else:
        q = copy.deepcopy(manifest["qualification"])
        q["sites"]["accept"] = False
        q = seal({k: v for k, v in q.items() if k != "sha256"})
        with pytest.raises(InvalidEvidence, match="does not follow"):
            validate_qualification(profile, manifest["binding"], q)


def test_declared_health_cannot_override_native_controls(installed):
    manifest, _, _ = installed
    manifest["health"]["sites"]["accept"] = False
    with pytest.raises(InvalidEvidence, match="retained qualification"):
        capture(manifest)


def test_archive_does_not_retarget_after_plugin_removal(installed, monkeypatch):
    manifest, _, _ = installed
    bundle = capture(manifest)
    expected = audit(bundle)
    monkeypatch.setattr("zerorun_harness.extensions.metadata.distributions", lambda: [])
    assert audit(bundle) == expected
    with pytest.raises(InvalidEvidence, match="exactly one"):
        capture(manifest)


@pytest.mark.parametrize(
    "field,value",
    [("id", "different-policy"), ("version", "2.0.0"), ("extra", "unrecognized")],
)
def test_archive_selection_must_match_embedded_policy(installed, field, value):
    manifest, _, _ = installed
    bundle = capture(manifest)
    bundle["extension"][field] = value
    changed = seal({k: v for k, v in bundle.items() if k != "sha256"})
    with pytest.raises(InvalidEvidence, match="extension"):
        audit(changed)


def test_ambiguous_registration_refused(installed, monkeypatch):
    manifest, _, dist = installed
    other = copy.copy(dist)
    other.metadata = {"Name": "different-domain-distribution"}
    monkeypatch.setattr(
        "zerorun_harness.extensions.metadata.distributions", lambda: [dist, other]
    )
    with pytest.raises(InvalidEvidence, match="exactly one"):
        load_extension(manifest["extension"])


def test_repeated_search_path_is_one_physical_installation(installed, monkeypatch):
    manifest, profile, dist = installed
    monkeypatch.setattr(
        "zerorun_harness.extensions.metadata.distributions",
        lambda: [dist, copy.copy(dist)],
    )
    assert load_extension(manifest["extension"]) == profile


@pytest.mark.parametrize(
    "value",
    [
        "domain:checker",
        "domain:../profile.json",
        "domain:profile.json [extra]",
        "domain:../x/profile.json",
    ],
)
def test_executable_or_unsafe_registration_refused(installed, value):
    manifest, _, dist = installed
    dist.entry_points[0].value = value
    with pytest.raises(InvalidEvidence):
        load_extension(manifest["extension"])


NATIVE_API = """def run(corrupt=False):
    identity = lambda i: dict(run='run-1', candidate='candidate-1', obligation=i, phase='base', attempt=1)
    # This exposed API owns its native state, rather than invoking the observer,
    # source binder or production relationship checker to obtain reference facts.
    facts = []
    for i, accepted in enumerate([True, False]):
        stored = not accepted if corrupt else accepted
        facts += [dict(kind='decision', identity=identity(i), values={'accepted':accepted, 'disposition':'accepted' if accepted else 'rejected'}),
                  dict(kind='commit', identity=identity(i), values={'stored':stored}),
                  dict(kind='serialized', identity=identity(i), values={'flag':int(stored)})]
    facts.append(dict(kind='aggregate', identity=identity(1), values={'accepted':False}))
    return {'inventory':[identity(0),identity(1)], 'facts':facts, 'native_complete':True}
"""


@pytest.mark.parametrize("corrupt,expected_exit", [(False, 0), (True, 1)])
def test_generated_native_assertions_need_no_framework(
    installed, tmp_path, corrupt, expected_exit
):
    manifest, _, _ = installed
    bundle = capture(manifest)
    native = tmp_path / "native"
    native.mkdir()
    (native / "native.py").write_bytes(SOURCE.encode())
    (native / "native_api.py").write_bytes(NATIVE_API.encode())
    recipe = dict(
        schema="zerorun-extension-native-recipe/1",
        source_files={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in native.glob("*.py")
        },
        module="native_api",
        function="run",
        args=[],
        kwargs={"corrupt": corrupt},
        reference_origin_sha256="2" * 64,
        justification="Exposed independently specified native API control",
    )
    script = tmp_path / "regression.py"
    script.write_text(
        export(bundle, mode="native-regression", recipe=recipe), encoding="utf-8"
    )
    out = tmp_path / "out.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(out),
        ],
        capture_output=True,
        timeout=15,
    )
    assert proc.returncode == expected_exit, (proc.stdout, proc.stderr, out.read_text())
    result = json.loads(out.read_text())
    assert result["classification_dependency"] is False and result["native_calls"] == 1
    assert result["result"] == ("PASS" if expected_exit == 0 else "FAIL")
    # Exclusive output protection must happen before native code on retry.
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--source",
            str(native),
            "--output",
            str(out),
        ],
        capture_output=True,
        timeout=15,
    )
    assert proc.returncode != 0 and json.loads(out.read_text()) == result


def test_native_script_does_not_embed_classifier_output(installed, monkeypatch):
    manifest, _, _ = installed
    bundle = capture(manifest)
    recipe = dict(
        schema="zerorun-extension-native-recipe/1",
        source_files={
            **bundle["binding"]["original_sources"],
            "native_api.py": "a" * 64,
        },
        module="native_api",
        function="run",
        args=[],
        kwargs={},
        reference_origin_sha256="2" * 64,
        justification="Exposed reference",
    )
    original = export(bundle, mode="native-regression", recipe=recipe)
    monkeypatch.setattr(
        "zerorun_harness.extensions.audit",
        lambda b: {"records": [{"status": "CORRUPTED"}]},
    )
    assert export(bundle, mode="native-regression", recipe=recipe) == original


@pytest.mark.parametrize("value", [None, [], {}, True, 1, 2.5, "", "bad"])
@pytest.mark.parametrize("field", ["api", "identity", "facts", "sites", "rules"])
def test_profile_envelope_mutations_refused(installed, field, value):
    _, p, _ = installed
    p[field] = value
    with pytest.raises(InvalidEvidence):
        validate_profile(p)
