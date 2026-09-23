"""Original Inspect native reference; no ZeroRun production imports or checks.

The authored scorers are finite fixtures, not a scientific cohort. Native task
execution creates partial score maps and native reducer/metric APIs consume them.
The tracer preserves actual caller populations and raw native serialized values.
It is a development reference, not a qualified generic source binding.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

PIN = "f9837f6c577da1bf89223f0575d4cb218940a79f"
SOURCE_PATHS = ["_eval/task/run.py", "_eval/task/results.py", "scorer/_metric.py", "scorer/_reducer/reducer.py"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--order", choices=["a-before-b", "b-before-a"], required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    runner_source = Path(__file__).read_bytes()
    (args.output / "runner-source.py").write_bytes(runner_source)
    started = time.perf_counter()
    import inspect_ai
    from inspect_ai import Task, eval as native_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, frequency, scorer
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai._eval.task import results as native_results
    from inspect_ai._util.registry import registry_log_name

    package = Path(inspect_ai.__file__).resolve().parent
    source_files = {}
    for path in SOURCE_PATHS:
        installed = package / path
        original = args.source / "src/inspect_ai" / path
        actual = hashlib.sha256(installed.read_bytes()).hexdigest()
        expected = hashlib.sha256(original.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError("Installed native source differs from pinned clone: " + path)
        source_files[path] = {"sha256": actual, "installed": str(installed), "original": str(original)}

    @solver
    def no_generation():
        async def solve(state: TaskState, generate: Generate):
            return state
        return solve

    @scorer(metrics=[accuracy(), frequency(categories=[0.0, 1.0])])
    def scorer_a() -> Scorer:
        async def score(state: TaskState, target: Target):
            identity = {"sample_id": state.sample_id, "epoch": state.epoch, "fixture_scorer": "a"}
            if state.sample_id == 3:
                return Score.unscored(reason="fixture_a_unscored", metadata=identity)
            return Score(value=0.0 if (state.sample_id, state.epoch) == (1, 2) else 1.0, metadata=identity)
        return score

    @scorer(metrics=[accuracy(), frequency(categories=[0.0, 1.0])])
    def scorer_b() -> Scorer:
        async def score(state: TaskState, target: Target):
            identity = {"sample_id": state.sample_id, "epoch": state.epoch, "fixture_scorer": "b"}
            if (state.sample_id, state.epoch) == (2, 1):
                raise RuntimeError("authored finite scorer error")
            if (state.sample_id, state.epoch) == (1, 2):
                return None
            if (state.sample_id, state.epoch) == (1, 1):
                return Score.unscored(reason="fixture_b_unscored", metadata=identity)
            return Score(value=0.0 if state.sample_id == 2 else 1.0, metadata=identity)
        return score

    traces = []
    native_file = str(Path(native_results.__file__).resolve())

    def sample_snapshot(samples):
        # Native Score serialization preserves NaN as its native JSON token.
        # It is opaque raw evidence here, not an eligibility flag or expected answer.
        return [{"sample_id": s.sample_id, "sample_metadata": s.sample_metadata,
                 "scorer": s.scorer, "score_wire": s.score.model_dump_json()} for s in samples]

    def trace(frame, event, arg):
        if frame.f_code.co_filename != native_file:
            return trace
        name = frame.f_code.co_name
        caller = frame.f_back
        caller_native = caller is not None and caller.f_code.co_filename == native_file
        context = {"native_function": name, "native_line": frame.f_lineno,
                   "caller_function": caller.f_code.co_name if caller else None,
                   "scorer": caller.f_locals.get("scorer_name") if caller_native else None,
                   "view": caller.f_locals.get("reducer_name") if caller_native else None}
        if event == "call" and name == "call_metric":
            traces.append({**context, "boundary": "native_metric_input", "metric": registry_log_name(frame.f_locals["metric"]),
                           "samples": sample_snapshot(frame.f_locals["sample_scores"])})
        elif event == "call" and name == "reduce_scores":
            traces.append({**context, "boundary": "native_reducer_input", "samples": sample_snapshot(frame.f_locals["scores"])})
        elif event == "return" and name == "reduce_scores":
            traces.append({**context, "boundary": "native_reducer_return", "samples": sample_snapshot(arg)})
        return trace

    scorers = [scorer_a(), scorer_b()]
    if args.order == "b-before-a":
        scorers.reverse()
    task = Task(dataset=[Sample(id=i, input="fixed authored control", target="unused",
                                metadata={"control_sample": i}) for i in [1, 2, 3]],
                solver=no_generation(), scorer=scorers, epochs=2)
    old_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        logs = native_eval(task, model="mockllm/model", fail_on_error=False,
                           display="none", log_dir=str(args.output / "native-logs"), max_samples=1)
    finally:
        sys.settrace(old_trace)
    if len(logs) != 1:
        raise RuntimeError("Expected one complete native evaluation log")
    log = logs[0]
    native_wire = log.model_dump_json()
    (args.output / "native-log.json").write_text(native_wire, encoding="utf-8")
    (args.output / "consumer-boundaries.json").write_text(json.dumps(traces, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    samples = [{"sample_id": s.id, "epoch": s.epoch, "error": s.error is not None,
                "scores": {name: score.model_dump_json() for name, score in (s.scores or {}).items()}}
               for s in sorted(log.samples or [], key=lambda s: (str(s.id), s.epoch))]
    summary = {"schema": "inspect-native-development-reference/1", "source_revision": PIN,
               "order": args.order, "native_status": log.status, "native_sample_records": len(samples),
               "samples": samples, "native_results_wire": log.results.model_dump_json() if log.results else None,
               "source_files": source_files, "native_version": importlib.metadata.version("inspect_ai"),
               "python": sys.version, "platform": platform.platform(), "optimize": sys.flags.optimize,
               "native_log_sha256": hashlib.sha256(native_wire.encode()).hexdigest(),
               "runner_sha256": hashlib.sha256(runner_source).hexdigest(),
               "duration_seconds": time.perf_counter() - started,
               "framework_semantic_modules_imported": [name for name in sys.modules if name.startswith("zerorun_harness")],
               "model_usage": {name: usage.model_dump() for name, usage in log.stats.model_usage.items()},
               "scope": "Authored native scoring/consumer controls; no independent extension, research owner, primary cohort or arithmetic correctness claim"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"native_status": log.status, "samples": len(samples), "boundary_records": len(traces),
                      "model_usage": summary["model_usage"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
