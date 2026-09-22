# Reproducing the reported evidence

The public `research/observations/` captures contain all 676 new saved application observations: 328 HumanEval task/bank records per exposed version and ten archived SWE records per component version. They contain native boolean/status records and hashes, not candidate source or benchmark input banks. Use the installed `audit`, `export`, `compare` and `report` operations directly on these files. The original acquisition scripts are supplied under `research/`; they execute only when a user explicitly runs them in the required isolated environment. The release CLI itself has no candidate-execution operation.

The application-summary and whole-population check preserve both the native outcomes and corrected interpretation. The `REPAIR_R1.md` disclosure explains the observation-coverage and native-preservation correction after the initial runs. This is exposed, source-informed solo development; the corrected replay is not a blinded validation or an independently authored study.

To acquire the original programs/data, use these exact sources and identities:

- EvalPlus HumanEval candidate asset: https://github.com/evalplus/evalplus/releases/tag/v0.1.0 ; `gpt-4-1106-preview_temp_0.0.zip`, asset 137360609, SHA256 `cad51c9c1d1f0491adc79cbb5739e10891472497e391d510cbd27ed9707b6015`.
- Native HumanEvalPlus input archive v0.1.9: exact upstream URL and data identity in the accompanying source manifest; SHA256 `e62f4130146963d969da64553f407a66e52d095adbfed4ee6733b4d59e14a3ed`.
- EvalPlus source revisions `c05b20b24ab6783878d9ffa1ae5496e83da0e65b` and `6eb1e199c2e370518e7bf3e8eee6322c2b23c89c`; canonical trusted execution at `4c79d0728f61d6b503a59abc12050392204c8fc0`.
- SWE experiments snapshot https://github.com/SWE-bench/experiments/tree/05ad61feb9c9f334dc340baea7c4f31cf7854274 ; Lite archives `20231010_rag_claude2` and `20231010_rag_gpt35`.
- Official SWE-bench Lite dataset pin `6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2`; ten record identities and all log URLs are retained in source manifests. Native component versions are `a5ecda6640d13f89848a3dceaa08585431d258db` and `489a34eb8c99f123e6af5f3ea8f3a8e8db85710b`.

Native execution requires a Linux Docker container with Python 3.11.16, numpy 1.26.4, psutil 5.9.8, unidiff 0.7.5, appdirs 1.4.4, tempdir 0.7.1 and wget 3.2. Use a single serial worker, 4-CPU quota/affinity, 6 GiB RAM, no swap, no network, non-root user, read-only inputs/root and bounded temporary storage. Exact package/image identities and mount contracts accompany the evidence. A fresh execution can have different timing outcomes; the native and observed runs in this study already demonstrate sensitivity to runtime perturbation.

Do not interpret saved-log component analysis as fresh patch execution. All ten selected logs lack both markers expected by both pinned harness versions. That observed incompatibility precludes a resolution-rate comparison under this route; the native default `RESOLVED_NO` is not a justified statement that all patches failed.
