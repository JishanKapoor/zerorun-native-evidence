# EvalPlus native parent/worker path reproduction

This directory contains inspectable acquisition, original-source reference, qualification, and raw-audit recipes. It executes the native `untrusted_check` parent and its original `Process(target=unsafe_execute, ...)` worker. The two producers belong to one actual invocation. Original-reference and observed invocations are separate executions and are compared by explicit source, candidate, phase, and input identities.

These are **authored controls on previously exposed sources**, including deliberate source faults. They are not a fresh historical study, independent-user evaluation, or model benchmark. No candidate dataset is packaged or downloaded by the recipe. Do not substitute control counts for scientific sample counts.

## Pinned inputs and environment

| Input | Exact version |
| --- | --- |
| EvalPlus before source | `c05b20b24ab6783878d9ffa1ae5496e83da0e65b` |
| EvalPlus after source | `6eb1e199c2e370518e7bf3e8eee6322c2b23c89c` |
| Native source module | `evalplus/eval/__init__.py` from `https://github.com/evalplus/evalplus.git` |
| Interpreter and process method | Linux amd64, CPython 3.11.16, `fork`, optimization level 0 |
| Native third-party dependencies | NumPy 1.26.4; psutil 5.9.8 |
| Python image | Digest in `Dockerfile.native.txt`; build asserts interpreter version |

The Dockerfile is a portable minimal recipe for these controls, not a claim that rebuilding it reproduces the previously retained image ID. Retain the image inspection and `/dependency-install.json` from each build. The historical engineering runs used image `zerorun-s2:validation` with retained ID `sha256:c7c8800893d4523ea839f47c7ee752518322462bb98bec5758f392fc7b86c663`; that image also had unrelated validation dependencies.

`prepare.py` seals every copied original `.py` dependency, every transformed module, the profile, source binding, lifecycle envelope, control inventory, and executing package/helper sources. Wildcard constants come from the original pinned `evalplus/config.py`. Neither reference execution nor the standalone native regression imports framework observers or uses their verdict as a native fact.

## Fresh checkout and preparation

Run the following in Bash on a Docker-capable Linux host, from the release repository root containing `src/` and `validation/`. Use a new writable work directory for every preparation or run. Only source retrieval and image building need network access; execution is offline. Choose a CPU affinity set with four available CPUs if `0-3` is unavailable.

```bash
set -eu
RELEASE_ROOT="$PWD"
WORK="$PWD/reproduction-evalplus"
mkdir "$WORK"
mkdir "$WORK/native" "$WORK/output"
git init --bare "$WORK/evalplus.git"
git -C "$WORK/evalplus.git" remote add origin https://github.com/evalplus/evalplus.git
for pin in c05b20b24ab6783878d9ffa1ae5496e83da0e65b 6eb1e199c2e370518e7bf3e8eee6322c2b23c89c; do
  git -C "$WORK/evalplus.git" fetch --depth=1 origin "$pin"
  test "$(git -C "$WORK/evalplus.git" rev-parse FETCH_HEAD)" = "$pin"
  mkdir "$WORK/native/$pin"
  git -C "$WORK/evalplus.git" archive "$pin" | tar -x -C "$WORK/native/$pin"
done
docker build --platform linux/amd64 -t zerorun-evalplus-native:local \
  -f validation/evalplus_path/Dockerfile.native.txt validation/evalplus_path
docker image inspect zerorun-evalplus-native:local > "$WORK/image.json"

# A non-root container must be able to create artifacts in this dedicated folder.
# On a host whose UID differs from 1000, assign this new work folder to UID 1000.
docker run --name zr-evalplus-prepare --user 1000:1000 \
  --cpus 4 --cpuset-cpus 0-3 --memory 6g --memory-swap 6g \
  --pids-limit 128 --network none --read-only --tmpfs /tmp:rw,size=128m,mode=1777 \
  -e PYTHONPATH=/release/src -v "$RELEASE_ROOT:/release:ro" \
  -v "$WORK/native:/native:ro" -v "$WORK/output:/output:rw" \
  zerorun-evalplus-native:local python /release/validation/evalplus_path/prepare.py \
  --native-sources /native --output /output/prepared
docker cp zr-evalplus-prepare:/dependency-install.json "$WORK/dependency-install.json"
```

The UID note concerns only the newly created reproduction directory. Do not recursively change ownership on a repository or unrelated files. Preparation makes no native bank calls. Inspect `output/prepared/design.json` before running: the full main inventory declares 204 actual bank calls. Preparation and campaign output directories must not already exist; preserve all failed attempts.

## Bounded native campaigns

This Bash helper executes one immutable preparation with a separate output mount, retains stdout/stderr, exit status and Docker state, and kills the container if its outer deadline expires. It does not mount the author package checkout. Runtime package imports come from the preparation's hashed package snapshot. This is source-snapshot reproduction; distribution-installed reproduction is a separate qualification route.

```bash
run_native() {
  name="$1"; prepared="$2"; script="$3"; limit="$4"
  mkdir "$WORK/output/$name"
  set +e
  timeout --signal=TERM --kill-after=10s "$limit" docker run --name "$name" \
    --user 1000:1000 --cpus 4 --cpuset-cpus 0-3 --memory 6g --memory-swap 6g \
    --pids-limit 128 --network none --read-only --tmpfs /tmp:rw,size=128m,mode=1777 \
    -e PYTHONPATH=/prepared/package -e PYTHONPYCACHEPREFIX=/tmp/pycache \
    -v "$prepared:/prepared:ro" -v "$WORK/output/$name:/results:rw" \
    zerorun-evalplus-native:local python "$script" /prepared /results/campaign \
    > "$WORK/output/$name/stdout.txt" 2> "$WORK/output/$name/stderr.txt"
  status=$?
  if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
    docker kill "$name" > "$WORK/output/$name/kill.txt" 2>&1
  fi
  printf '%s\n' "$status" > "$WORK/output/$name/exit-code.txt"
  docker inspect "$name" > "$WORK/output/$name/container.json"
  set -e
  return "$status"
}
run_native zr-evalplus-main "$WORK/output/prepared" \
  /prepared/implementation/evalplus_path/campaign.py 1200s
```

The main campaign compares 111 original/observed scenario pairs: 102 pairs that execute a bank, and 9 preflight-error pairs that execute no bank. It checks 18 declared site labels per source scenario, across 9 source realizations. `qualification_controls` in retained JSON means **site-by-scenario qualification comparisons** (1,998 for the full inventory), not independent test cases. There are 162 source/site declarations and 204 physical binding anchors. A deliberate missing commitment or wrong native aggregate is expected to yield a violation; expected failures are verified, not hidden or relabeled as passing native outcomes.

Run the stdlib-only raw auditor on the host; it launches no native processes and imports no framework code:

```bash
python validation/evalplus_path/audit_path.py \
  --prepared "$WORK/output/prepared" --campaign "$WORK/output/zr-evalplus-main/campaign" \
  --output "$WORK/main-raw-audit.json"
```

## Large banks and standalone exports

The following preparation uses the checked-out framework to seal new large-bank and export artifacts. It reuses the completed main campaign's qualification receipts. It makes zero native calls. For exact runtime reproducibility, run these Python commands inside the same pinned image with read-only release/native inputs and a dedicated writable output mount, as in the initial preparation. Host execution requires the package installed or `PYTHONPATH` pointing at this release's `src/` directory.

```bash
export PYTHONPATH="$RELEASE_ROOT/src"
python validation/evalplus_path/prepare_large.py \
  --source "$WORK/output/prepared" --prior "$WORK/output/zr-evalplus-main/campaign" \
  --output "$WORK/output/large-prepared"
python validation/evalplus_path/prepare_exports.py \
  --prepared "$WORK/output/prepared" --campaign "$WORK/output/zr-evalplus-main/campaign" \
  --output "$WORK/output/export-prepared"
run_native zr-evalplus-large "$WORK/output/large-prepared" /prepared/campaign.py 360s
run_native zr-evalplus-exports "$WORK/output/export-prepared" /prepared/campaign.py 180s
python validation/evalplus_path/audit_followups.py \
  --large-prepared "$WORK/output/large-prepared" \
  --large-campaign "$WORK/output/zr-evalplus-large/campaign" \
  --export-prepared "$WORK/output/export-prepared" \
  --export-campaign "$WORK/output/zr-evalplus-exports/campaign" \
  --output "$WORK/followups-raw-audit.json"
```

Large-bank controls execute 128 and 1,000 authored inputs on both original revisions: four original/observed pairs, eight actual bank calls, 2,256 scenario-specific input positions, and 4,512 original-plus-observed input visits. Values and prefixes repeat across sizes and revisions. Generated-model outputs remain zero. The optional `--dataset-count-inventory FILE` accepts an external retained count inventory for capacity comparison only; it is not required and does not load a candidate dataset.

Standalone exports execute four additional original banks. Each generated `regression.py` runs in isolated mode, loads the frozen original source and independent `native_recipe.py`, and imports no framework. Expected overall results are before-`find_zero` FAIL, after-`find_zero` PASS, authored reversed parent details FAIL, and external timeout UNASSESSABLE. The campaign verifies exact per-relationship agreement, including non-applicable inventory products; its 49 assertion records are not 49 independent scientific effects.

The public package also contains `transport_qualification.py` and `transport_adapter.py` for separately frozen lifecycle/failure controls. These authored process controls are not EvalPlus bank calls. The retained transport campaign includes supervisor death before `setsid`, a dead group leader with a surviving descendant, buffer mismatch, and missing/lost/flooded channels. Every new transport freeze must pin adapter, supervisor, qualification, and installed transport bytes before execution.

## Bounds and evidence semantics

- Large cases use one source-hashed JSON file (8 MiB maximum), with duplicate keys/non-finite data refused. Inputs and native returned details are not truncated to the 64-element control-message limit; large native results are stored as exact bytes in a hashed artifact.
- Native input inventory is bounded at 4,096, primary semantic events at 16,384, and the finite profile's conservative `6*n+6` event bound can reject a bank before the inventory limit. Total transport budget is 16 MiB split equally between the two producers; exact frame bounds can impose a smaller accepted population. Tested capacity is 1,000 inputs per bank, not an arbitrary-size claim.
- A semantic event, a batch control frame, a lifecycle packet, a site comparison, a relationship record and a native bank invocation are different units. Per-producer sequence/PID integrity and completed batch membership qualify absence. A lost worker does not invalidate an independently complete parent-local status mapping.
- Physical writes are checked against independent CPython opcode transitions and actual post-store state, including false writes. Parent/worker shared-buffer linkage is exact fork-inherited wrapper/backing identity within one capture, never address equality across runs.
- Primary policies use finite existence, identity, conjunction, status membership, guarded mapping and complete native batch membership. Exact progress arithmetic is a separate ordinary/reference qualification assertion; it is not a new generic arithmetic operator or a blanket primary proof.
- Preserve original/transformed source bytes, native results, raw journals, all qualifications, transport/lifecycle receipts, expected violations, timeouts and failed preparations. Re-auditing receipts makes zero native calls. Passing these controls establishes the documented engineering scope, not external peer review or submission approval.
