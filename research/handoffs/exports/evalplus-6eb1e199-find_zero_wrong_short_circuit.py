# SPDX-License-Identifier: MIT
"""Generated standalone native component regression. No ZeroRun runtime required.

Run only in an appropriate isolated environment: EvalPlus executes the embedded
candidate. This is a pinned component handoff, not an end-to-end benchmark run.
"""
import argparse
import hashlib
import importlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import tempfile
import types

PAYLOAD = json.loads('{"capture_sha256":"d0f96a2c54c01670e6a6a12e549ba2f4a15af0f893dedb0d3e180b2f858bc8bd","family":"evalplus","level":"native-component-regression","provenance":{"candidate_sha256":"e8f0e59e04134a603b7752705fc58729240a2513f84370c7346a9f2b862c7254","input_sha256":"d6e30c8552664f6b5560bf4753158d3180561f87b869ad7430860a3296823a47","source_sha256":"3c833c39b842e33f251c83db4347e0a95191909f23b390c12d73ab29a28a4daf"},"recipe":{"input":{"atol":1e-06,"code":"def find_zero(xs):\\n    return 1.0\\n","dataset":"humaneval","entry_point":"find_zero","expected":[0.0,0.0],"fast_check":true,"inputs":[[[0.0,1.0]],[[0.0,2.0]]],"time_limits":[1.0,1.0]},"maintenance_action":"Protect native complete rejection, ordinary acceptance and permitted short-circuit commitment under the exposed fixture.","record_id":"find_zero_wrong_short_circuit","reference":{"details":[false,false],"progress":1,"worker_status":1},"reference_origin_sha256":"63bb2e07401d8aefbd6be2812d269c0ff8afd4158af5aeae787073dc531df0a0","reference_sha256":"7e9da441a2766311abe9f0dfeef8901fe5d2da02b006f39da914edcd335d8cc8","role":"policy-protection","schema":"zerorun-native-recipe/1","source_files":{"evalplus/__init__.py":"fd8bd103579e95d9a9114272caf122360d6957c5ee4d67dc047884fefe0c48c2","evalplus/config.py":"dc14b4400cbf05d5bcab5b94d785f046cca22b0dbc10bc9756f8356dc42f18e3","evalplus/eval/__init__.py":"3c833c39b842e33f251c83db4347e0a95191909f23b390c12d73ab29a28a4daf","evalplus/eval/_special_oracle.py":"92b126b907ee493121b55de06f6a34058b6e18adc8cf1c48737eedcd83f24cdd","evalplus/eval/utils.py":"0aec25f437dbc7637219ba749ba71921670e71cd2e70b1cc23988896c0754bb1"}},"record_sha256":"228125b84d30e3d642a328d102f99b974d10488f3b3a77520e26faf03e229207","schema":"zerorun-native-handoff/1","template_sha256":"dc9ebcfcb7f4c7967bf6b5e47d8793d2e187cc678f8c28c7d29899cb32deaaba"}')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def execute(source, verified):
    recipe = PAYLOAD["recipe"]
    inventory = recipe["source_files"]
    prefix = "evalplus" if PAYLOAD["family"] == "evalplus" else "swebench"
    actual = {p.relative_to(source).as_posix() for p in (source/prefix).rglob("*.py")}
    if actual != set(inventory):
        raise ValueError("Native Python source inventory mismatch")
    for relative, expected in inventory.items():
        p = source/relative
        data = p.read_bytes()
        if not p.resolve().is_relative_to(source) or p.is_symlink() or sha(data) != expected:
            raise ValueError("Native source identity mismatch: " + relative)
        destination = verified/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
    # Import only copied verified source: stale or poisoned bytecode is excluded.
    source = verified
    sys.dont_write_bytecode = True
    if sha(encoded(recipe["reference"])) != recipe["reference_sha256"]:
        raise ValueError("Native reference identity mismatch")
    inp = recipe["input"]
    if sys.flags.optimize != 0:
        raise ValueError("Optimized native execution is unsupported")
    if PAYLOAD["family"] == "swe":
        if sha(inp["log"].encode("utf-8")) != PAYLOAD["provenance"]["input_sha256"]:
            raise ValueError("Native input identity mismatch")
        # Bypass unrelated package-root Docker setup; native components unchanged.
        for name, rel in [("swebench", "swebench"), ("swebench.harness", "swebench/harness")]:
            module = types.ModuleType(name)
            module.__path__ = [str(source/rel)]
            sys.modules[name] = module
        native = importlib.import_module("swebench.harness.grading")
        native_types = importlib.import_module("swebench.types")
        spec = native_types.TestSpec(**inp["spec"], image="component-only", eval_script_list=[], eval_type="pass_and_fail")
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/"log.txt"
            log.write_bytes(inp["log"].encode("utf-8"))
            selected, found = native.get_logs_eval(spec, str(log))
        report = native.get_eval_tests_report(selected, {k:inp["spec"][k] for k in ("FAIL_TO_PASS", "PASS_TO_PASS")})
        resolution = native.get_resolution_status(report)
        result = {"selected":selected, "found":found, "report":report, "resolution":resolution}
        calls = {"native_component_entry_calls":3, "authored_candidate_bank_calls":0}
    else:
        if sha(inp["code"].encode("utf-8")) != PAYLOAD["provenance"]["candidate_sha256"] or sha(encoded(inp["inputs"])) != PAYLOAD["provenance"]["input_sha256"]:
            raise ValueError("Native candidate or input identity mismatch")
        if sys.platform != "linux" or "fork" not in mp.get_all_start_methods():
            raise ValueError("Native worker regression requires qualified Linux fork")
        sys.path.insert(0,str(source))
        native = importlib.import_module("evalplus.eval")
        ctx = mp.get_context("fork")
        stat, progress = ctx.Value("i",native._UNKNOWN), ctx.Value("i",0)
        details = ctx.Array("b",[False]*len(inp["inputs"]))
        proc = ctx.Process(target=native.unsafe_execute, kwargs={**inp,"stat":stat,"progress":progress,"details":details})
        proc.start()
        try:
            proc.join(sum(inp["time_limits"])+5)
            if proc.is_alive():
                raise RuntimeError("Native outer timeout; no qualified assertion")
            if proc.exitcode != 0 or stat.value not in (native._SUCCESS,native._FAILED):
                raise RuntimeError("Incomplete native worker; no qualified assertion")
            result = {"worker_status":stat.value,"progress":progress.value,"details":[bool(v) for v in details[:]]}
        finally:
            if proc.is_alive():
                proc.kill()
                proc.join(5)
        calls = {"native_component_entry_calls":0, "authored_candidate_bank_calls":1}
    # Type-preserving comparison: e.g. false must never equal integer zero.
    matches = encoded(result) == encoded(recipe["reference"])
    return {"result":"PASS" if matches else "FAIL", "native":result,
            "reference":recipe["reference"], "calls":calls,
            "native_module":str(Path(native.__file__).resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    # Reserve output before any native call; never rerun merely to overwrite it.
    try:
        stream = args.output.open("x",encoding="utf-8",newline="\n")
    except OSError as exc:
        print(str(exc),file=sys.stderr)
        return 2
    with stream:
        result = {"schema":"zerorun-native-regression-result/1", "level":PAYLOAD["level"],
                  "role":PAYLOAD["recipe"]["role"], "payload_sha256":sha(encoded(PAYLOAD)),
                  "python":sys.version, "optimize":sys.flags.optimize,
                  "uid":os.getuid() if hasattr(os,"getuid") else None,
                  "classification_dependency":False}
        try:
            with tempfile.TemporaryDirectory() as directory:
                result.update(execute(args.source.resolve(),Path(directory)))
            code = 0 if result["result"] == "PASS" else 1
        except Exception as exc:
            result.update(result="UNASSESSABLE",error=type(exc).__name__+": "+str(exc))
            code = 2
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"result":result["result"],"output":str(args.output)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
