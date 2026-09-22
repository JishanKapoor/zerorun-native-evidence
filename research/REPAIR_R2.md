# R2: public API boundary corrections, 22 September 2026

The user stopped PDF production and requested code and evidence verification before manuscript formatting. Further outputs are Markdown and executable verification evidence. Previously preserved PDFs and plan documents remain unchanged; no new PDF is authorized at this stage.

Review of release 0.2.1 found four concrete defects. Nineteen prospective regression cases were added before the fixes; the old code failed eighteen and passed one. The original code snapshots and failure report are retained under `study_s2/evidence/r2/`.

1. Malformed `health` data reached a `.get()` call in native agreement and crashed the public audit/export/compare/report path. The semantic checker had already handled this input, so checker-only fuzzing missed the API failure. Exact dictionary validation now yields an unavailable agreement diagnostic and the existing evidence restriction.
2. The internal terminal monitor event expanded the whole native state after its `kind` field. Extra native metadata could overwrite monitor control flow, causing a crash or false conformance for contradictory primitive state. Only validated progress and boolean cells now enter the internal terminal event. Original native metadata remains in the sealed bundle.
3. Native-value agreement allowed Python's integer/boolean equality to imply agreement for non-boolean committed cells. It now requires exact boolean types.
4. SWE native agreement could report agreement for two equally malformed maps. Both maps must now use the declared primitive native status vocabulary.

Release 0.2.2 adds these corrections without changing native acquisition, cohort selection, source profiles, ordinary/native scores, or the earlier recorded audit files. A new verification compares all 676 saved records to their retained audits. The independently implemented ordinary qualification route receives the same stricter input contract, with no production semantic imports. New boundary controls exercise the complete public API and label invariance, not merely monitor functions.

These controls are software robustness tests. They do not count as R11's unfamiliar native challenge sets, six historical pairs, independent projects, operator participation, or recurring-effort evidence. No native candidate rerun is authorized by this correction: S2's 1,312-call candidate-bank allocation has already been consumed.
