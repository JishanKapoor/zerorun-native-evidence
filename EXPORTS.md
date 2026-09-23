# Export levels and native handoffs

Version 0.4.0 adds explicit export levels to the existing `export` API/CLI. Export generation itself starts no native process. Running a generated native script does execute the native component and, for EvalPlus, the supplied candidate; use the documented isolated Linux environment.

| Mode | Output | Runtime dependency | Interpretation |
|---|---|---|---|
| `native-values` (default) | Existing schema-2 JSON projection | None to read | Native values, references and qualifications side by side |
| `event-replay` | Complete schema-1 capture JSON | ZeroRun to audit it | Exact saved evidence, without recapture |
| `integration-replay` | Python script embedding the capture | Installed ZeroRun | Workbench-dependent re-audit; not a native regression |
| `native-regression` | Standalone Python script with recipe, references and source inventory | Pinned native evaluator and its dependencies; no ZeroRun | Component-level comparison of actual native values with an explicit independent native reference |

```python
from zerorun_harness import export
saved = export(bundle, mode="event-replay")
integration_script = export(bundle, mode="integration-replay")
native_script = export(bundle, mode="native-regression", recipe=recipe)
```

```sh
zerorun export capture.json --mode event-replay --output replay.json
zerorun export capture.json --mode integration-replay --output integration.py
zerorun export capture.json --mode native-regression --recipe recipe.json --output native.py
python native.py --source /pinned/native/tree --output new-result.json
```

Use new output paths. Native script exit codes are 0 for a satisfied native reference assertion, 1 for an assessable contradiction, and 2 for an input/source mismatch, unsupported runtime or incomplete native execution. They are not model acceptance scores. A defect reproducer should fail on a known defective revision and pass on the independently qualified corrected revision. A policy-protection regression can pass on both. Neither role proves a whole-pipeline result.

## Recipe contract

The exact recipe keys are `schema`, `record_id`, `role`, `maintenance_action`, `source_files`, `input`, `reference_origin_sha256`, `reference`, and `reference_sha256`. The schema is `zerorun-native-recipe/1`. `record_id` must identify one capture record. `role` is `defect-reproducer` or `policy-protection`; the maintenance action describes why preserving the native relationship matters. Arbitrary callback/checker code is not accepted as a recipe.

`source_files` maps every Python file under `evalplus/` or `swebench/` to its SHA256. The primary module must match the retained record and an existing supported profile. Runtime verifies the exact native Python inventory and copies verified bytes into a fresh directory before importing them, excluding old bytecode. This pins native Python code, not every third-party dependency; native dependency/image identities belong to the separately retained execution environment. Unknown source versions require a newly qualified profile.

`reference_origin_sha256` identifies the independently acquired source record from which reference values were selected; `reference_sha256` binds the exact typed reference object. The generator validates content identities, not the truth, independence or adequacy of the declared reference. The researcher must retain and qualify its origin. The study scripts reconstruct references directly from retained native acquisition records and verify those origin hashes. Reference values never come from a ZeroRun status label.

For **SWE**, `input` contains exact UTF-8 `log` text and `spec` with `instance_id`, `repo`, `version`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `log_parser`. Log bytes must match the capture input hash; the full recipe additionally binds the task inventory. The script invokes unchanged `get_logs_eval`, `get_eval_tests_report`, and `get_resolution_status`. Package-root initialization is bypassed to avoid unrelated Docker-building setup. Returned selected map, admission flag, four-category report and resolution are compared with the reference. It executes no patch or test suite. Missing historical markers remain missing; export never inserts them.

For **EvalPlus**, `input` contains `dataset`, `entry_point`, `code`, `inputs`, `expected`, `time_limits`, `atol`, `fast_check`. Only the exposed HumanEval native worker interface is supported. Candidate UTF-8 bytes and canonical JSON input-list bytes must match capture provenance. Exact boolean fast-check and nonnegative finite tolerance are required. Banks contain 1–100,000 argument lists; individual limits are positive and at most 10 seconds, with at most 60 seconds total. The script calls unmodified `unsafe_execute` under Linux `fork`, optimize=0, using caller-owned primitive shared state. It compares raw worker status, progress and all boolean cells. Worker-loop status alone is not acceptance. Incomplete worker exit/outer timeout is unassessable. No canonical outputs are recomputed by the generator.

The generated script embeds the capture, record, recipe and template identities in its payload. Its receipt records that payload's digest, actual native values, expected native values, result, Python version, optimization flag, user identity and native call counts. Exact typed JSON comparison prevents booleans from aliasing integer values. Existing result files are refused before native execution. A source/input/reference identity failure also precedes native calls.

## Qualification scope

The accompanying S4 engineering campaign uses four already exposed authored EvalPlus fixtures at two revisions and the original ten SWE logs at two revisions. It is separate from the fixed S2 cohort experiment. Generated source is byte-identical when the ZeroRun classifier is replaced with corrupted output. Its native executions run with ZeroRun unavailable. The exposed polynomial-root commitment regression can reproduce the known before/after difference; it is not a new defect discovery or unfamiliar historical-transfer result.

These exports close an implementation omission. They do not establish R11's complete consequential historical worksheets, independent scientific adoption, measured work savings or independently authored extension. Those study conditions require their own evidence and cannot be inferred from successful script execution.
