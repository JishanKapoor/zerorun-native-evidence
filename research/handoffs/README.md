# Standalone component handoffs

These 28 scripts use two pinned revisions per native family, four exposed authored EvalPlus fixtures, and ten original archived SWE logs. `inputs/export-index.json` identifies scripts and the exact expected exit under the declared native fixture reference. `reference-origins/` contains the retained independent native acquisition records, named by byte SHA256. Native source code is not bundled here; acquire the exact revision named in each index source path using the instructions in `../../NATIVE_ACQUISITION.md` (repository root).

Run the selected script with `python SCRIPT.py --source /exact/native/repository --output /new/result.json` inside the isolated native environment documented at repository root. EvalPlus scripts require Linux fork and execute authored candidates. SWE scripts execute three native saved-log components and no patch. All native Python source bytes are verified before imports. The installed ZeroRun package is unnecessary to run these artifacts.

For `evalplus-c05b20b2-find_zero_correct`, expected exit 1 is deliberate reproduction of the exposed original commitment defect; its corrected-revision counterpart exits 0. Other scripts exit 0. Exit 2 indicates a source/environment/input problem and does not count as reproduction. Original SWE marker rejection is retained, never converted into patch failure or a claimed repaired marker.

To regenerate a script, install ZeroRun 0.4.0 and use the corresponding capture/recipe files with `zerorun export CAPTURE --mode native-regression --recipe RECIPE --output NEW.py`. No native execution occurs at generation. Source template and input identities must remain unchanged for byte-for-byte generation.

These are post-study engineering controls. They do not add new primary cohort candidates, independent human operators or unfamiliar historical cases. The original benchmark observations remain in `../observations/`. Original SWE log material comes from the official SWE-bench submission archives; original code and data retain their upstream attribution. See the repository's third-party notices and native acquisition source manifest.
