# Native paths and identity in 0.8.0

The five public operations retain their existing interfaces. Native acquisition
uses separate, explicit recipes. Importing a capture or replaying an audit does
not run a candidate. Native recipes do run the declared original evaluator, and
must use the resource-limited environment recorded for that recipe.

## Versions and admission

| Binding grammar | Contract |
| --- | --- |
| 1.0.0 | Original finite structural sites and primitive projections |
| 1.1.0 | Nested functions, finite container/shared-memory paths and single-evaluation return observations; see the historical native-internals page |
| 1.2.0 (default) | Compound ancestry selectors, multiple views at a statement, bounded materialized native batches and finite collection projections |
| 1.3.0 (explicit opt-in) | Ordinary async scopes, declared stored record fields, per-item scientific identities, separate acquisition ordinals and per-invocation activation identity |
| 1.4.0 (explicit opt-in) | Explicit lexical class-method selectors and annotated fields inherited from same-source bases or assigned to the instance in its original initializer |

Pass the explicit `grammar_version` to `generate_binding(profile, sources, ...)`
to request an opt-in contract. A new feature cannot be supplied to an older grammar.
Always preserve the binding's original grammar when regenerating saved
evidence. Source, profile, binding, engine, export and runtime identities remain
separate. Guarded, batch-aware or producer-scoped interpretations identify
engine 1.1.0; unchanged older records retain their original engine identity.

## Native batch and scientific identity

A site may declare `"batch": {"local": "scores", "max_items": 4096}` for an
already materialized exact list or tuple. Acquisition snapshots that sequence;
it does not repeat a native computation, iterate an arbitrary user object or
invent missing elements. The callback emits a begin record, one event per
element, and an end record. Empty lists have their own zero-size receipt.

The older ordinal identity uses `{"ordinal": true}`. For records whose actual
stored sample ID is the scientific key, grammar 1.3 instead permits
`"ordinal": "acquisition"` in the batch declaration and an identity projection
such as:

```json
{"item":true,"path":[{"record":"sample_score","stored":"sample_id"}]}
```

The profile must declare that exact record and field. The event's separate
`acquisition` object contains its batch identifier and zero-based position.
Reordering does not rename a scientific sample. Duplicate scientific identities
remain visible. Group receipts omit per-item keys; an empty list never creates
a fictitious sample ID. Element identity projections cannot use a default,
encoding or coercion to repair an absent stored ID.

`extract_batches(profile, binding, payloads)` validates exact provenance,
element order and controls. Its receipt alone does not certify native completion
or transport. A lost end preserves the acquired positive facts and an incomplete
batch. A fully witnessed independently frozen inventory can still support its
own relation; an incomplete batch cannot supply an absence/completeness premise.

## Registered stored fields and numeric values

`register_records(profile, binding, classes)` verifies the loaded module/class
identity against original source declarations. Pass its immutable registry as
`records=` to `recorder`. Only exact registered instances and declared fields in
their native instance dictionaries are read. Properties, serializers, custom
attribute lookup and metaclass equality are not invoked. Changed inheritance,
class shape, invalid storage or an absent field rejects the observation.

The `number_json` encoding preserves bounded exact integer/float values as
tokens, including `NaN`, infinities and signed zero. It neither labels an
unscored result as a failure nor silently substitutes zero. Domain-specific
meaning remains in the declared policy and separately qualified native route.

## Async execution and activation

Ordinary async function sites record values only when the selected statement
actually executes. An after-await observation follows a successfully completed
await; cancellation or an exception does not invent the missing commitment.
Selected generators and decorated async functions remain outside this finite
grammar.

An identity projection `{"activation": true}` requires an integer identity
field. It adds one reserved local at actual function entry, after the docstring.
Recursion, concurrent coroutines and repeated invocations receive different
tokens; multiple sites across an await retain the same token. Creating an
unstarted coroutine does not allocate a token. Tokens are bounded to 32,768 per
recorder and scoped to its producer/binding; they are not scientific sample IDs
or cross-function join keys. Wrapper callbacks must forward the recorder's
`.enter` method.

Direct local introspection (`locals`, zero-argument `vars` or `dir`, `eval`, `exec`),
their supported attribute/import forms and finite simple aliases are refused
in activation scopes, including nested definition-time expressions. This is a
finite syntax guard, not a proof against arbitrary opaque reflection. Original
versus observed native qualification remains necessary.

Grammar 1.4.0 additionally accepts explicit `Class.method` lexical selectors,
including nested classes. It injects the callback name `__zr_observe__`, whose
ending double underscore prevents Python class-name mangling. Native loaders
must install the recorder under that exact name. Reserved return and activation
temporaries likewise end in double underscores; recorder normalization changes
only those reserved keys. Existing grammars keep their exact old callback names.
Known local introspection is also refused for 1.4 return-value temporaries.

Inherited field declarations must resolve through explicit same-source class
definitions without a decorated or syntactically rebound base identity.
Initializer declarations must be annotated assignments to the
first instance parameter in the original nondecorated `__init__`; nested scopes,
other objects and unannotated assignments do not supply declarations. No missing
imported base field is guessed. Runtime registration continues to require exact
native class/storage identity and refuses changed inheritance or descriptors.

## Completion, producer health and guards

Two-producer capture uses `capture_native_pair` and independent parent/worker
channels installed before the native fork and reliability guard. A parent
return does not imply worker completion. Lifecycle completion, physical
transport integrity and semantic site coverage are separate recorded premises.
`producer_role` binds sites to the actual parent or worker PID; a rule depends
on the health of its producer, consumer and guard sites.

A finite guard is `{"kind": "native_status", "field": "value", "in": [...]}`.
Missing or ambiguous guard evidence is unknown. A qualified false guard records
that the rule is inapplicable; it is not an observed successful obligation.
`inventory_policy: "complete_batch_membership"` may add a completeness premise
from exactly one matching complete native batch with the required health.
It does not repair lost transport or ambiguous populations.

## Source-distribution recipes

| Directory | Native route |
| --- | --- |
| `validation/evalplus_path` | Original bank invocation, original worker shared buffers and actual parent slicing/status; independent original reference, large-bank, transport and standalone-export controls |
| `validation/swe_reporting` | Original `run_instance(..., rewrite_reports=True)` writer and original `make_run_report` saved-file reader/aggregate |
| `validation/swe_joined` | Same-invocation original parser, F2P/P2P partitions, grading, writer, reader and aggregate |
| `validation/inspect_path` | Source-pinned async scorer commitment, native Score/SampleScore storage, raw/reduced populations and original metric selection; qualification receipts determine completed scope |
| `validation/pytest_native` | Original pytest source loader, authored phase controls and independent public TestReport hook records; qualification is separate from a benchmark patch run |
| `validation/swe_pytest` | Real pytest phase/terminal evidence and the original SWE saved-log chain in the same acquisition process; raw stdout and the separate SWE marker wrapper retain distinct hashes |

The SWE saved-log routes do not execute a benchmark Docker patch/test run.
The Inspect recipe uses authored controls and a solver without model generation.
Development source revisions and authored fault controls are not unfamiliar
historical cases or independent project adoption. Consult the particular
recipe's README and retained source/runtime/call ledger before reproducing it.

Declarative standalone export version 2 accepts independently acquired native
facts, exact inventory, per-rule native completion and native batch receipts.
Acquisition-mode batches require explicit ordinals. Generated scripts use native
values and the sealed policy rather than an embedded previous verdict; they run
without the ZeroRun package. A recipe invocation count is not automatically a
native bank count. The actual native entry journal supplies that denominator.
