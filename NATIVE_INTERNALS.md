# Native internal observation, binding grammar 1.1.0

This page records the 0.7.0 / grammar-1.1 qualification scope. For the current 0.8.0 interfaces and native paths, read [Native paths and identity](NATIVE_PATHS.md).

Version 0.7.0 extended the common source binder and bounded primitive projections. Its engine and export semantics remain version 1.0.0. Saved grammar 1.0.0 bindings regenerate with their original grammar; the default for newly generated bindings in 0.7.0 was 1.1.0. An exact binding digest continues to distinguish source and observation policy.

## What is observed

The source distribution includes executable qualification tools, finite declarations, independently implemented native reference recipes, authored inputs and licensed source fixtures. These tools are under `validation/evalplus_internal` and `validation/swe_internal`; they are not automatically discovered extensions in the core wheel. Install the core wheel and use the source-distribution tools and exact upstream dependency trees to reproduce native qualification. Each family README documents preparation and execution.

EvalPlus observations enter the actual acceptance, caught-rejection, shared-array write, progress update, worker-loop completion and parent-grade paths. `worker_loop_completed` names the native loop status and does not imply candidate acceptance. Native reference runs use unchanged upstream functions, standard-library tracing and caller-owned shared memory. Direct-worker and parent-grade captures are correlated separate executions, not one end-to-end trace. C1 checks commitment presence, C2 checks boolean/byte preservation, and C3 checks committed byte membership against native grade. Executed controls check raw progress against references; the common engine does not implement a general arithmetic counter invariant.

SWE observations enter the actual pytest parser decision and dictionary writes, first/fallback parser returns, selected/consumed map, nested F2P/P2P decisions and list commitments, returned/consumed report, native fractions, resolution and final report return. An authored JSON round trip is an explicit downstream artifact boundary. This component campaign does not execute Docker patch evaluation or the upstream final JSON writer, and does not qualify arbitrary concurrent pytest phase reconciliation.

The two exposed source revisions per family and authored mutations are development qualification. They do not constitute the prospectively selected six historical pairs, unfamiliar 48-variant challenge campaign or independent operator study.

## Finite projection syntax

Native fields may project a primitive literal, a local or the evaluated return operand. Paths contain at most eight steps: a fixed string/integer `index`, an `index_local` (optionally selected by at most four fixed `index_path` segments), or approved ctypes scalar `member: value`. Ordinary indexing accepts exact built-in dict/list/tuple objects and exact standard ctypes or synchronized arrays. Custom indexing, properties, model objects, arbitrary calls and user-defined ctypes subclasses are refused.

```json
{"local":"details","path":[{"index_local":"i"}]}
{"local":"progress","path":[{"member":"value"}]}
{"local":"report","path":[{"index":"FAIL_TO_PASS"},{"index":"success"}],"encoding":"json"}
{"return":true,"path":[{"index":0}],"encoding":"json"}
```

JSON snapshots are bounded to 4,096 nodes, depth eight, 32 dictionary entries, 64 list entries and 1,024-character strings. Only exact wire primitives and finite numbers are supported. A primitive `default` applies only to a missing valid native container index. It does not mask an unknown local, unsupported object or invalid selector.

Identity fields alone may use `{"context":"run"}`. `recorder(..., context={...})` validates and snapshots the exact declared primitive context before execution. Context cannot supply native facts or shadow native locals.

Recorder construction also snapshots the validated declaration and binding identity, so later caller edits cannot change a live callback's interpretation. Synchronized wrappers must retain their standard instance fields and built-in semaphore methods. The projector validates the exact native lock and backing object and reads through the native semaphore directly; altered wrapper methods are refused without invocation.

## Structural sites and evaluation order

Grammar 1.1.0 supports dotted lexical nested-function selectors, `before`/`after` simple statements, `try_success`, `handler_entry`, `before_return` and `return_value`. A before-return site executes before evaluation of the return expression. A return-value site evaluates the original operand once, records that value, then returns the same object. Python `finally` may subsequently override that return; the event describes the operand at the declared site, not an assertion about the eventual function result. Untouched lambdas may remain in source. Async and generator scopes remain unsupported.

Reserved callback/temporary/local-access names are checked across assignments, arguments, imports, scope declarations, exception targets and pattern captures. A wildcard import is accepted only when its exact supplied dependency module contains literal constant assignments and an optional literal `__all__`; exported names must not collide with reserved plumbing. Arbitrary namespace initialization is refused. Malformed transformations are reported as unsupported bindings.

Source identity, branch qualification, completion and transport health are separate premises. A skipped pre-decision input is not an observed acceptance. Missing seals or forced termination cannot establish absence-based violations. Retained raw references and qualified positive/negative witnesses are necessary to support each native semantic interpretation.
