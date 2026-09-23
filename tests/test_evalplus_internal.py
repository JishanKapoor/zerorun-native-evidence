"""Portable checks of actual native-source bindings; Linux execution is separate."""

import ast
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

from zerorun_harness.api import InvalidEvidence
from zerorun_harness.binding import generate_binding, validate_binding
from zerorun_harness.declarative import validate_profile

FOLDER = Path(__file__).resolve().parents[1] / "validation" / "evalplus_internal"
sys.path.insert(0, str(FOLDER.parent))
spec = importlib.util.spec_from_file_location("evalplus_internal_profiles", FOLDER / "profiles.py")
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)
spec2 = importlib.util.spec_from_file_location("evalplus_internal_prepare", FOLDER / "prepare.py")
preparation = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(preparation)


def source_inventory(source):
    return {profiles.NATIVE_PATH: source, "evalplus/config.py": (FOLDER / "sources" / "config.py").read_bytes().decode()}


@pytest.fixture(params=["before", "after"])
def native_source(request):
    return request.param, (FOLDER / "sources" / (request.param + ".py")).read_bytes().decode("utf-8")


def test_retained_native_source_identities(native_source):
    label, source = native_source
    assert hashlib.sha256(source.encode()).hexdigest() == {"before": "76857b678cddca08dcaf54d7927b9a77826715cf657654ca5baf6c2b267f4c34", "after": "3c833c39b842e33f251c83db4347e0a95191909f23b390c12d73ab29a28a4daf"}[label]


def test_actual_native_binding_regenerates(native_source):
    label, source = native_source
    p = profiles.parent_profile(source)
    b = generate_binding(p, source_inventory(source))
    assert validate_binding(p, b)
    assert p["sites"]["true-commit"]["multiplicity"] == (1 if label == "before" else 2)
    assert p["sites"]["progress-write"]["multiplicity"] == (2 if label == "before" else 3)
    assert b["original"][profiles.NATIVE_PATH] == source
    assert b["original_sources"] != b["transformed_sources"]


def test_acceptance_sites_are_specific_passed_native_assertions(native_source):
    _, source = native_source
    p = profiles.parent_profile(source)
    for name in ["accept-exact", "accept-tolerant", "accept-polynomial"]:
        s = p["sites"][name]
        assert s["position"] == "after"
        assert isinstance(ast.parse(s["anchor"]).body[0], ast.Assert)
    assert not any(s["position"] == "try_success" for s in p["sites"].values())
    assert p["sites"]["worker-loop-completed"]["kind"] != "decision"


def test_bound_native_writes_are_not_created(native_source):
    _, source = native_source
    p = profiles.parent_profile(source)
    b = generate_binding(p, source_inventory(source))
    original = ast.parse(source)
    transformed = ast.parse(b["transformed"][profiles.NATIVE_PATH])

    def writes(tree):
        return [ast.dump(n, include_attributes=False) for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AugAssign))]

    # before_return may introduce a return-value temporary, but native stores
    # and increments must each remain exactly once, with unchanged RHS.
    native_writes = [w for w in writes(original) if "details" in w or "progress" in w]
    bound_writes = [w for w in writes(transformed) if "details" in w or "progress" in w]
    assert native_writes == bound_writes


def test_unrecognized_commit_structure_refused(native_source):
    _, source = native_source
    p = profiles.parent_profile(source)
    changed = source.replace("details[i] = False", "details[i] = 0")
    with pytest.raises(InvalidEvidence):
        generate_binding(p, source_inventory(changed))


def test_changed_native_progress_arithmetic_is_not_silently_bound(native_source):
    _, source = native_source
    p = profiles.parent_profile(source)
    changed = source.replace("progress.value += 1", "progress.value += 0")
    with pytest.raises(InvalidEvidence):
        generate_binding(p, source_inventory(changed))


def test_candidate_invocation_and_comparisons_not_duplicated(native_source):
    _, source = native_source
    binding = generate_binding(profiles.parent_profile(source), source_inventory(source))

    def calls(text):
        return sorted(ast.dump(n, include_attributes=False) for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call) and (ast.unparse(n.func) in {"fn", "np.allclose", "_poly"}))

    assert calls(source) == calls(binding["transformed"][profiles.NATIVE_PATH])


def test_independent_reference_does_not_import_framework_or_profiles():
    tree = ast.parse((FOLDER / "reference.py").read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert not any(name and (name.startswith("zerorun") or name in {"profiles", "adapter"}) for name in imports)


@pytest.mark.parametrize("variant", ["pre-decision-skip", "accepted-commit-omission", "rejected-commit-omission"])
def test_authored_variants_preserve_native_write_anchors(variant):
    source = (FOLDER / "sources" / "after.py").read_bytes().decode()
    variant_source = preparation.variants(source)[variant]
    p = profiles.parent_profile(variant_source)
    b = generate_binding(p, source_inventory(variant_source))
    assert validate_profile(p) == p
    assert b["original"][profiles.NATIVE_PATH] == variant_source
    assert "continue" in variant_source
    assert p["sites"]["false-commit"]["multiplicity"] == 1
    assert p["sites"]["true-commit"]["multiplicity"] == 2


def test_profile_has_no_hidden_expected_grade_or_executable_checker(native_source):
    _, source = native_source
    p = profiles.parent_profile(source)
    assert {r["check"] for r in p["rules"]} == {"C1", "C2", "C3"}
    assert {r["operator"] for r in p["rules"]} == {"exists", "bool_to_int", "all_in"}
    assert all(set(s["projection"]) == set(p["identity"]) | set(p["facts"][s["kind"]]) for s in p["sites"].values())
    changed = copy.deepcopy(p)
    changed["rules"][0]["expected_grade"] = "pass"
    with pytest.raises(InvalidEvidence):
        validate_profile(changed)
