# Finite native relationships and installed declarations

Release 0.6.0 adds `zerorun.extensions/1`, selected through the existing five API/CLI operations. It evaluates C1 required commitments, C2 typed decision/serialization preservation and C3 conjunction/status-set derivability. Declarations cannot return executable checkers. The provided separate `zerorun-exposed-domain` distribution is framework-authored development material, not the independent Inspect extension study required by R11 I3–I6.

## Installed selection and component identities

A separately installed distribution registers entry points in `zerorun.extensions.v1`. An entry's name is the extension ID; its value is `package.name:profile.json`. The framework reads the packaged JSON through distribution metadata and checks its content digest and distribution/profile version. It never calls `EntryPoint.load()` or imports extension code to register a profile. Missing/ambiguous registrations, unsafe paths, resource changes, unsupported schemas and executable checker registrations are refused.

For example, the separate declaration distribution uses:

```toml
[project.entry-points."zerorun.extensions.v1"]
exposed-native = "zerorun_exposed_domain:profile.json"
```

Five identities remain separate: common engine 1.0.0; domain policy ID/version/content digest; generated binding grammar 1.0.0 or 1.1.0 and binding digest; native export template 1.0.0; and case-material version/digest. Policy, original source, transformed source, runtime, controls and case facts are not interchangeable identities. Archived captures embed their declarations and bindings; removing or upgrading an installed extension cannot silently retarget old observations. Interpretation runs produce separate content-identified reports.

## Finite grammar

Profiles require `api`, `id`, `version`, `identity`, `facts`, `sites`, `rules` and `justification`. Exact primitive identity types are string, integer, boolean and finite float; run, candidate, obligation, phase/bank and attempt are mandatory. Booleans cannot equal integers through Python's permissive equality. Additional fields are allowed only when declared. There are at most 12 identity fields, 32 fact kinds, 32 fields per kind, 64 observation sites and 64 relationships. Case inventories have 1–4,096 unique identities; observation inventories have at most 16,384 events. Duplicate identities or ambiguous matching cannot become a confident absence accusation.

Each rule declares its producer, consumer, native matching keys, optional finite native-disposition status set, source/target fields, supported operator, coverage dependencies and native justification. No arbitrary predicate, `eval`, author expected grade, opaque eligibility computation or plugin checker is accepted.

- C1 requires a uniquely matched logical commitment for each applicable observed native disposition. A pre-decision skip does not create an acceptance obligation. Missing commitments violate only with qualified required sites, relevant completion and intact transport.
- C2 compares two observed native fields under exact identity, boolean-to-integer conversion or integer-0/1-to-boolean conversion. An out-of-domain integer conversion is unsupported.
- C3 supports conjunction and status-set membership over a declared native inventory. Optional explicit native status mappings distinguish true, false and incomplete aggregate outcomes; unknown statuses are unsupported. Missing all-true operands cannot establish acceptance. A witnessed false operand determines conjunction under legitimate failure-prefix termination, even when later native inputs are not visited.

Successful aggregate interpretation is not candidate mathematical correctness. Native loop completion is never renamed candidate acceptance. The provided EvalPlus API profile observes returned details and the actual parent grade; the SWE API profile observes native report membership and the actual resolution string. These profiles do not infer the unobserved internal worker/parser paths.

## Structural binding and qualification

Grammar 1.0.0 is described below; [grammar 1.1.0](NATIVE_INTERNALS.md) additionally supports finite paths, shared memory, nested functions and return sites. `binding.generate_binding(profile, sources, grammar_version="1.0.0")` accepts UTF-8 source text preserving original newline bytes. Source keys are safe relative `.py` paths; each supplied source is at most 1 MiB and the inventory has at most 32 files. Binding declarations use exact executable AST statement anchors inside a uniquely named top-level function, a declared static multiplicity of 1–16, native local/primitive-literal projections, and one supported position: after a simple native statement, successful completion of a `try` body, or entry into its single declared handler. Native expressions are not evaluated twice and native writes are never supplied. A `try` success hook does not run after a caught exception, pre-decision continue or return.

Missing/ambiguous anchors, overlapping declarations, unsupported control-flow shapes, generator/async scopes, or shadowed callback plumbing are refused. Bindings retain original and transformed source, their byte hashes, actual source lines, AST-anchor hashes and static multiplicities. Validation regenerates the binding from the original source and frozen declarations; manually retargeted/rehashed transformations are refused. This is a finite structural grammar, not arbitrary Python instrumentation or proof that a chosen site means what its author claims.

Native acquisition uses the separately documented [bounded transport](TELEMETRY.md). Its qualified native runtime is Linux CPython 3.11.16/fork/optimize=0. Portable source/wire/data tests on other interpreters do not qualify native capture there. Native glue may call native APIs and expose their primitive returned facts; derived semantic determinations belong in visible finite declarations. The caller must audit glue and native dependency provenance. A source digest alone does not establish an honest or sufficient adapter.

`qualification.qualify(profile, binding, controls)` compares complete typed native identity/value references to actual observed controls. Every site needs a positive witness; branch-sensitive success/handler sites additionally need negative controls. References preserve native source, reference recipe and output identities and disclose whether production semantics were imported. Missing callbacks, wrong identities and invalid success paths disqualify their sites. Certificates are rebuilt from retained controls at capture/audit time; a caller cannot replace the resulting site states with a more favorable health flag. These are conditional operational qualification records, not automatic proofs or independent study-adjudication references.

Reports retain native completion by relationship, transport integrity by producer and semantic coverage by site. Missing premises suppress absence accusations. A positively witnessed contradiction at qualified sites remains visible despite an unrelated gap. Failures on separate relationships are returned as incomparable rather than inventing a cross-producer total order.

## Public Python workflow

The separately installed profile supplies domain meaning. The acquisition wrapper supplies primitive native facts, and separately retained native references qualify the observation sites. The following workflow uses the same selection as the CLI:

```python
from zerorun_harness import capture, audit, compare, export, report
from zerorun_harness.extensions import load_extension
from zerorun_harness.binding import generate_binding
from zerorun_harness.qualification import qualify

policy = load_extension(selection)  # id, version, sha256
binding = generate_binding(policy, original_native_sources)
certificate = qualify(policy, binding, native_control_records)
manifest = {
    "schema": "zerorun-extension-manifest/1",
    "extension": selection, "binding": binding, "case": case_material,
    "observations": observed_native_events, "qualification": certificate,
    "health": {
        "binding_sha256": binding["sha256"],
        "qualification_sha256": certificate["sha256"],
        "sites": certificate["sites"],
        "transport": producer_transport_states,
        "native_complete": relationship_completion_states,
    },
}
bundle = capture(manifest)
result = audit(bundle)
delta = compare(bundle, bundle)
native_values = export(bundle)
readable = report(bundle)
```

`validation/verify_extension_install.py` executes the fully populated workflow, actual installed metadata discovery, all five CLI operations and both replay levels outside the author package. `validation/example_extension` is a complete separately buildable distribution, not a new sixth command. `InvalidEvidence` is the public malformed/unsupported-data exception; the CLI reports it with exit 2 and protects existing output files.

## Three reproduction levels

Event replay contains prepared native events, case inventory, policy and health; `declarative.evaluate` reproduces its interpretation. Integration replay contains the complete captured binding/qualification envelope; `audit` reconstructs its qualification and interpretation with the framework. Neither reruns native candidates.

Native regression export accepts a source-pinned native API recipe and emits a standalone standard-library assertion script. Run it in the native dependency environment with `--source ROOT --output NEW.json`. It verifies original source bytes, loads source rather than cached bytecode, calls the declared native entry point, and evaluates the finite assertions over raw inventory/facts/completion. It does not import ZeroRun or embed classifier outputs. Return codes are 0 for a passing relationship, 1 for an observed contradiction and 2 for unassessable execution; native interruption is retained in the receipt. Original sources, unmodified native API glue, native dependency environment and conditional assertion qualification remain necessary. An authored glue function returning a hidden validity answer is outside the interface's scientific contract even if it lies about provenance.

## Compatibility and qualification boundaries

The original `zerorun-capture/1` interface and its 676 saved determinations remain unchanged. The extension interface is a new schema with explicit policy/binding versions. New operators, binding grammar, source realizations or native policies require new versions and qualification records. The supplied API profiles qualify finite development cases on their pinned sources; they do not deliver complete internal decision-to-commitment bindings for every native branch, six unused historical pairs, independent participants, measured human-work savings or a submission-ready R11 study. Those requirements must be assessed on their own actual evidence.
