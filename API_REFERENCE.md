# ZeroRun Harness 0.5.0 API and operating boundaries

## Installation and execution

Install the wheel with `python -m pip install --no-index --no-deps <wheel>`. The runtime has no external package dependencies. The source distribution also supplies the ordinary comparator, software tests and boundary campaign; those validation commands require pytest 8.4.2. The installed package exposes `zerorun` and `python -m zerorun_harness`.

| Path | Supported contract | Executed verification |
|---|---|---|
| Saved-evidence Python API and CLI | Python 3.11 or later; exact finite JSON primitives; no candidate execution | Windows 3.12.14 and Linux 3.11.16 installed wheels; public CI matrix 3.11-3.14 |
| EvalPlus relationship | Three packaged exposed source-file hashes; sequential nonempty dispositions; typed boolean commitment prefix; optimize=0 | Authored controls and complete retained S2 captures |
| SWE relationship | Two packaged exposed source-file hashes; native admission plus observed parser maps; final selection preservation | Authored controls and all ten saved logs at both pinned versions |
| Original acquisition scripts | Linux fork and pinned native source/data in the declared isolated container | Historical S2 execution records; separate from the release CLI |

Python-version compatibility does not extend the qualified native source grammar. The matrix does not imply fresh benchmark execution on Windows or every CI interpreter. The historical acquisition observer is retained exactly; the package checks gaps in its saved observations. It is not an automatic, arbitrary-source native capture service.

## Manifest and bundle

`capture(manifest: dict) -> dict` accepts exactly one root field, `records`, containing 1-4,096 records. Each record has exactly:

- `id`: unique nonempty string, at most 1,024 characters.
- `family`: `evalplus` or `swe`.
- `provenance`: exactly `source_sha256`, `input_sha256`, `candidate_sha256`, each 64 lowercase hexadecimal characters.
- `observation`: JSON object in the declared finite grammar.
- `native_reference`: separately acquired JSON object or explicit `null`.

It returns `schema`, `mode`, `records`, `sha256`, with schema `zerorun-capture/1` and mode `saved-evidence`. The digest covers the canonical payload without its own hash field. Canonicalization sorts object keys, preserves list order, emits UTF-8 and accepts exact JSON types only. Maximum nesting is 64. NaN/infinity, cycles, surrogate encoding errors, non-string dictionary keys and implicit tuple conversion are rejected. A digest is an integrity check, not proof of a truthful producer or authentic execution.

## Observation fields

EvalPlus observations retain `source_sha256`; `events` with integer `seq`, integer `index`, `kind` (`accept`/`reject`) and integer `optimize` (0); one `seals` entry with `seal=true` and integer `attempted`, `emitted`, `dropped`; and `state` with exact boolean `details`, integer `progress`, integer `worker_status` (0/1). Health contains exactly the three booleans `native_complete`, `transport_intact`, `semantic_coverage`. `exitcode` must be integer zero and `outer_timeout` must be boolean false for qualified relationship checks.

Events form a contiguous, duplicate-free prefix starting at index zero. An intact seal requires attempted=emitted=event count and dropped=0. A committed prefix longer than the disposition prefix indicates missing observation; more dispositions than commitments can establish a qualified commitment violation. Extra metadata remains stored but cannot override internal monitor control fields. Primitive state values are compared directly; no mathematical oracle is reevaluated.

The optional EvalPlus native reference uses `grade` (`pass`, `fail`, `timeout`) and boolean `details`. Agreement is assessed only when the observed native completion/state is assessable. Raw worker status zero is loop completion, not candidate acceptance; acceptance additionally requires full commitment and all true cells.

SWE observations retain `source_sha256`, boolean `found`, boolean `observer_coverage`, a nonempty list `parser_calls` of native maps, and `selected`. Every map uses string identities and the native vocabulary `PASSED`, `FAILED`, `ERROR`, `SKIPPED`, `XFAIL`. An empty map is valid; missing parser observation or marker admission restricts qualification. A native reference may contain `selected` and other retained native fields; agreement requires valid primitive maps. The relationship compares selection with the final observed parser map and does not replace F2P/P2P policy or perform patch execution.

## Functions and outputs

Version 0.5.0 also accepts `export(bundle, mode=..., recipe=...)`; see [the exact export-level and native-recipe contract](EXPORTS.md). The default `native-values` mode and existing output schemas remain compatible. Other modes produce saved capture JSON, a workbench integration script or a standalone native component script. Export generation executes no native code; running the latter script does.

Version 0.5.0 emits `zerorun-audit/2`, `zerorun-compare/2` and `zerorun-native-export/2`. Input captures still use `zerorun-capture/1`. Retained version-1 audit files belong to the earlier engine and remain available as historical outputs; do not edit their schema tag to claim migration.

Audit and export include `native_agreement_fields`: the fields within the declared comparison scope. A null agreement means those premises are unassessable; an empty field list with a null reference means no independent comparison was supplied. EvalPlus compares native grade/details. SWE always requires valid selected maps and additionally checks `found`, `report` and `resolution` when supplied by the reference. All four native report categories must contain typed success/failure identity lists. Valid resolution strings are `RESOLVED_NO`, `RESOLVED_PARTIAL`, `RESOLVED_FULL`. The checker compares native values; it does not recompute grading policy.

Compare includes `identity_alignment` (`MATCHED`, `MISMATCH`, `MISSING`) and `identity_mismatches`. Matching record IDs alone are insufficient: family, candidate SHA256 and input SHA256 must also match. Different source revisions are allowed. Matching identities do not imply valid native qualification; both per-side statuses remain visible.

Export includes `native_fields`, preserving the supplied SWE selected map, admission, report and resolution or the EvalPlus primitive worker state. The legacy `native_state` projection remains available. Neither field replaces native scores with audit labels.

| Function | Output and guarantee |
|---|---|
| `audit(bundle)` | Digest-validated per-record `status`, underlying `relationship_status`, nullable `native_agreement`, reasons and evidence/source hashes; complete inventory and counts |
| `compare(left, right)` | Union of IDs, both statuses, explicit `MISSING` on an absent side and `same_evidence`; does not silently intersect populations |
| `export(bundle)` | Per-record primitive native state, original reference, provenance and qualification side by side; no conversion of qualification to candidate score |
| `report(bundle)` | Deterministic plain-text counts and records; escaped record identities; includes scope boundary |

Qualification values are `CONFORMS`, `VIOLATION`, `INCONCLUSIVE`, `UNSUPPORTED`. An independently acquired native-value disagreement or an unassessable supplied reference restricts an otherwise conforming/violating relationship to `INCONCLUSIVE`; the raw relationship result remains visible. Absent references are explicit null agreement, never an independent-preservation claim.

Each function validates the complete supplied bundle. Invalid envelopes, SHA256 identity syntax, duplicate record IDs and digest mismatches raise `zerorun_harness.api.InvalidEvidence`. Malformed inner native observations produce the declared unsupported/restricted interpretation where the envelope is valid. None of these functions starts a native evaluator or a candidate subprocess.

## CLI and troubleshooting

All five commands require `input` and `--output`; `compare` also requires `other`. Inputs are UTF-8 JSON, capped at 64 MiB; duplicate JSON keys are refused. Outputs are created exclusively: choose a new output path rather than overwriting retained evidence. An I/O or validation error returns 2. A completed audit returns 0 even if it contains a violation. Neither process exit nor `CONFORMS` is a candidate pass score.

- Digest mismatch: recover the original complete capture; do not recompute a hash to disguise changed evidence.
- Unsupported source: use the declared pinned source and grammar, or establish a separately qualified profile; arbitrary allowlisting is not qualification.
- Observation gap or native disagreement: retain both results and use the independently adequate native route where available. Do not insert missing events or relabel timeouts as passes.
- SWE marker rejection: use evidence actually admitted by the declared native policy. Adding marker text to an old log without independently establishing its phases cannot reproduce a historical patch result.
- Existing output path: use a new versioned path. Earlier failures and analyses remain evidence.

Run `python -m pytest tests -q` and `python validation/boundary_campaign.py` from the source distribution after installing the wheel. Public `research/verify_observations.py` replays all 676 records; `research/native_consumer.py` checks all 174 scientific entries without production checker imports. These software checks consume no candidate-bank allocation.

## Native telemetry component

The separately invoked `zerorun_harness.telemetry.capture_native` API starts a fresh supervisor and native adapter under the qualified Linux runtime. Its exact limits, inputs, refusal states, wire protocol, errors and health boundaries are specified in [TELEMETRY.md](TELEMETRY.md). It is additional acquisition infrastructure; the five existing replay operations retain their contracts.
