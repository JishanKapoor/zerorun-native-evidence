# ZeroRun Harness 0.2.2

See [API and operating reference](API_REFERENCE.md) for exact record fields, supported modes, return values and troubleshooting. `Licence.txt` and `LICENSE.txt` contain the same new-code license; upstream vendor terms remain separately retained.

ZeroRun imports native evaluator observations into content-identified records and replays two bounded relationship checks. It preserves native values, independent reference outcomes, uncertainty and the entire supplied record population. It executes no candidate code.

This release is a narrower solo reproducibility utility, distinct from the earlier ZeroRun test-result-reuse software and from the stronger R11 independent-user study. It makes no adoption, human productivity, benchmark-wide performance or automatic source-transfer claim.

## Install

Python 3.11 or later. Install the provided wheel, offline:

```sh
python -m pip install --no-deps zerorun_harness-0.2.2-py3-none-any.whl
zerorun --version
```

No runtime packages need downloading: the unmodified pinned PyContract core is vendored with its Apache-2.0 license. New code is MIT licensed. The source distribution includes the independent ordinary-Python comparator and tests. The wheel includes source profiles, schema information and nine authored development observations, not third-party candidate programs or benchmark datasets.

## Five operations

```python
import json
from importlib.resources import files
from zerorun_harness import capture, audit, compare, export, report

manifest = json.loads(files('zerorun_harness').joinpath(
    'examples/development-manifest.json').read_text())
bundle = capture(manifest)
result = audit(bundle)
assert len(result['records']) == 9
print(report(bundle))
native_fields = export(bundle)
comparison = compare(bundle, bundle)
```

The corresponding CLI commands are:

```sh
zerorun capture manifest.json --output capture.json
zerorun audit capture.json --output audit.json
zerorun compare capture.json another-capture.json --output comparison.json
zerorun export capture.json --output native-export.json
zerorun report capture.json --output report.txt
```

Outputs must be new paths. CLI errors return exit code 2 and explain the reason; valid evidence with a violation is still a successfully produced audit, so exit code 0 is not a conformance verdict. Never derive candidate scores from process exit codes.

`capture` imports existing observations. Native acquisition was performed by separately retained experimental scripts in the research evidence package under isolated Docker restrictions. This CLI never starts a subprocess or executes/imports candidate source. SHA256 hashes bind retained bytes; they do not authenticate who produced the data or prove that a reported source was executed.

## Input and qualification

The input manifest contains a `records` list. Each record has exactly `id`, `family`, `provenance`, `observation` and `native_reference`. Provenance contains lowercase `source_sha256`, `input_sha256` and `candidate_sha256`; all are required. Record IDs must be unique and are preserved. The profiles in `resources/profiles.json` list accepted exposed source-file hashes. An unknown source or association mismatch yields `UNSUPPORTED`; adding arbitrary hashes is not qualification.

For EvalPlus, the observation contains ordered accept/reject events, a producer seal, primitive boolean native cells/progress/status, separate native-completion/transport/semantic-coverage flags, effective optimize=0 and process outcome. Unknown modes/types, duplicate/reordered identities and malformed seals cannot establish conformance. A native committed prefix longer than observed dispositions is an observation gap. More qualified dispositions than native commitments is a commitment violation. A native execution with no reached dispositions is outside this nonempty grammar.

For SWE, the finite check compares the last observed native parser-return map with the selected map and preserves the native status vocabulary (PASSED, FAILED, ERROR, SKIPPED, XFAIL). A missing marker/parser invocation produces uncertainty, not an invented failed patch. This check does not adjudicate arbitrary parser policies or replace native F2P/P2P interpretation.

Audit distinguishes `CONFORMS`, `VIOLATION`, `INCONCLUSIVE` and `UNSUPPORTED`. Malformed envelopes or content-digest mismatches raise `InvalidEvidence`. If a separately supplied native reference disagrees with observed native values, overall qualification is `INCONCLUSIVE`; the underlying relationship status and disagreement remain visible. Missing independent references are explicit nulls, not evidence of preservation. Exports retain raw native state, reference values and qualification side by side, without converting an audit label into a score. `compare` keeps missing records in the union of inventories.

## Validation and limitations

The release is checked using systematic boolean commitment cases, malformed-input/fault controls, full saved application records, a clean wheel installation and a second Python/platform environment. Exact executed test counts, native call counts, original failures and repairs are in the accompanying study records; repeated replay tests are not independent scientific replications.

The scientific application fixes 164 HumanEval completions and ten SWE archive records before their execution/analysis. The two EvalPlus versions and two SWE component versions were already exposed during development. Their results do not establish unfamiliar historical transfer. Observation can affect timing, and intact transport does not alone prove semantic coverage. Source-associated flags require a qualified producer; this cooperative evidence utility does not defend against malicious producer forgery or deceptive candidate return objects.

The nine bundled example records derive from authored fixtures. Their candidate hash identifies exact authored program bytes; their input hash identifies the complete authored fixture bundle. They are not the 164 real cohort programs. Those programs remain in the separately attributed local evidence bundle and official upstream archives.

## Reproduce software tests

From the source distribution, install pytest 8.4.2 in a test environment and run:

```sh
python -m pip install . --no-deps
python -m pytest tests -q
```

The ordinary comparator in `ordinary/checks.py` deliberately has no production-checker or PyContract import. Adequate ordinary/native helpers can supply the same determinations; this release claims evidence organization and explicit boundaries, not exclusive detection capability.
