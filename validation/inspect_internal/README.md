# Inspect native feasibility reference

These files investigate a concrete third relationship: partial scorer results and the scorer-specific population passed to native reducers and metrics. They are author/AI-owned exposed development materials. They do **not** implement or advertise an installed ZeroRun Inspect extension, independent extension study, independent research owner, or R11 I1 qualification.

The native source is [Inspect revision f9837f6c577da1bf89223f0575d4cb218940a79f](https://github.com/UKGovernmentBEIS/inspect_ai/tree/f9837f6c577da1bf89223f0575d4cb218940a79f), package version 0.3.268. The three selected, unmodified source fixtures are retained as text for exact source admission tests; they are not imported by portable tests. Copyright (c) 2024 UK AI Security Institute; the upstream MIT license is reproduced in `sources/INSPECT_LICENSE.txt`.

| Fixture | Original source path | SHA-256 |
| --- | --- | --- |
| `sources/run.py.txt` | `src/inspect_ai/_eval/task/run.py` | `9f6a4f63e82ed9f4a697045472eec26f59f652d8fce7199eb4e6f5aa9ed3950b` |
| `sources/results.py.txt` | `src/inspect_ai/_eval/task/results.py` | `83d905c8fcc27c9965e85921cd3a5c16bcbff2a70d5e72ac9d74157a5d1221c9` |
| `sources/metric.py.txt` | `src/inspect_ai/scorer/_metric.py` | `07f6a0397ea287053da39184d208842d2c1b1331564ade45b9cc1de0f432ef29` |

`feasibility.py` supplies structural probes against those exact bytes. The seven portable tests in `tests/test_inspect_internal.py` require no Inspect installation, skip no cases, and verify source identity and refusal boundaries. The current common grammar refuses the actual asynchronous scorer-commit function, arbitrary native model-field traversal, and nonfinite unscored values. These refusals are supported boundaries, not four qualified relationships.

`native_reference.py` separately runs original Inspect APIs with two authored scorers, three authored samples, two epochs, an identity solver, the local mock model, native mean reduction, accuracy and frequency metrics. It traces the original synchronous reducer and metric-call functions using the Python tracing API. It imports no ZeroRun production module and records installed/source byte equality, module origins, runtime, native logs, consumer input populations and its own source. No model generation is requested. The two scorer orders distinguish a retained earlier score from a score never reached after an error. A scorer returning `None` produces a missing entry; `Score.unscored()` retains the native NaN representation. Native numeric metric outputs are retained but are not independently validated arithmetic or research model results.

To repeat the development reference, create an isolated Python environment, clone the official repository at the exact revision above, install that checkout and install this release. Preserve the dependency lock and checkout identity. From the release directory, execute each command with that environment's Python and a new output directory:

```text
python validation/inspect_internal/native_reference.py --source /absolute/path/to/inspect-checkout --output /absolute/path/to/new-a-before-b-run --order a-before-b
python validation/inspect_internal/native_reference.py --source /absolute/path/to/inspect-checkout --output /absolute/path/to/new-b-before-a-run --order b-before-a
python validation/inspect_internal/fit_probe.py
```

`fit_probe.py` uses real installed Inspect values to report current grammar refusals. It is separate from dependency-free portable tests. Full upstream sources, the installed environment and native logs are not part of the ZeroRun runtime package. Study receipts identify the Windows environment used for the recorded development executions; this is not the qualified Linux native campaign of the primary adapters.

A meaningful future extension must expose the actual asynchronous commitment/error path and the synchronous consumer population, with lossless identity and unscored handling. A wrapper that exports the final native summary would not establish these internal relationships. Any change to async hooks or model projection requires a separately versioned grammar, qualification and freeze before claims. Inspect already supplies the [scoring policy](https://inspect.aisi.org.uk/scoring-policy.html) and [metrics](https://inspect.aisi.org.uk/metrics.html) used here; these existing capabilities are not claimed as new framework contributions.
