# Native acquisition and saved-evidence replay

Saved-evidence reproduction is the main reproducible release workflow. From the pinned Git checkout, install the release wheel, then run `python research/verify_observations.py` and `python research/native_consumer.py`. These reproduce all 676 determinations and the 174-entry native summary with zero candidate execution. The upstream archives and original calibration times are not needed for this replay.

The following separate procedure reconstructs native acquisition. It executes archived programs in a restricted container and can produce different timing outcomes. It does not replace the retained study observations or their historical identities. The preparation script only downloads/verifies bytes; it never executes candidates.

## Prepare the fixed inputs

Run from the versioned Git checkout with Python 3.11 or later:

```sh
python research/prepare_native_inputs.py --cache asset-cache --output native-inputs --download > native-inputs-receipt.json
```

This uses the exact URLs, byte counts and SHA256 identities in `research/source-manifest.json`. Twelve assets are needed: the candidate ZIP, input-bank gzip and ten original logs. A changed asset is rejected, never silently substituted. Each candidate ZIP member is also verified. The result contains 164 candidate programs, the full HumanEvalPlus input banks, two cohort manifests, ten logs and the log manifest. SWE task inventories and prediction hashes are reconstructed from the retained source manifest, without copying patch programs. No patch execution is part of this route. Upstream terms continue to apply.

For offline preparation, populate `asset-cache/<sha256>` with each matching asset and omit `--download`. Preparation requires a new output directory and exclusive file creation. If it fails, retain the partial output and use a new directory for a corrected attempt; it does not erase previous evidence.

## Sources and container mounts

Retrieve these exact Git revisions into five separate directories. Do not use current default branches:

| Directory | Upstream repository | Revision |
|---|---|---|
| `sources/reference` | `https://github.com/evalplus/evalplus` | `4c79d0728f61d6b503a59abc12050392204c8fc0` |
| `sources/eval-before` | `https://github.com/evalplus/evalplus` | `c05b20b24ab6783878d9ffa1ae5496e83da0e65b` |
| `sources/eval-after` | `https://github.com/evalplus/evalplus` | `6eb1e199c2e370518e7bf3e8eee6322c2b23c89c` |
| `sources/swe-before` | `https://github.com/SWE-bench/SWE-bench` | `a5ecda6640d13f89848a3dceaa08585431d258db` |
| `sources/swe-after` | `https://github.com/SWE-bench/SWE-bench` | `489a34eb8c99f123e6af5f3ea8f3a8e8db85710b` |

`git clone --no-checkout <repository> <directory>` followed by `git -C <directory> checkout --detach <revision>` supplies each complete upstream tree. Build `docker build -f research/Dockerfile.native -t zerorun-native-reproduction .`. The Dockerfile pins the base digest and Python dependencies; retain the resulting image identity and dependency-install report. Image construction requires networking; native execution disables it.

Run each operation serially using a single Linux Docker worker. Use a new, host-writable result directory for each operation; container UID/GID is 1000:1000. The common options are:

```sh
docker run --cpus 4 --cpuset-cpus 0-3 --memory 6g --memory-swap 6g \
  --pids-limit 128 --network none --read-only \
  --tmpfs /tmp:rw,size=128m,mode=1777 \
  -v "$PWD/sources/reference:/source:ro" \
  -v "$PWD/native-inputs/cohort:/cohort:ro" \
  -v "$PWD/research:/application:ro" \
  -v "$PWD/results/reference:/results:rw" \
  zerorun-native-reproduction python /application/canonical_reference.py
```

The shown command is the reference operation. Create `results/reference` first; run without Python optimization. Reference preparation makes 328 canonical-bank calls and writes integrity-identified local pickle files. Load only reference files produced by the trusted canonical operation, with its matching manifest.

| Operation | `/source` host directory | Script under `/application` | Additional read-only mount | Fresh `/results` directory |
|---|---|---|---|---|
| Reference | `sources/reference` | `canonical_reference.py` | None | `results/reference` |
| EvalPlus before | `sources/eval-before` | `evalplus_application.py` | `results/reference:/references` | `results/eval-before` |
| EvalPlus after | `sources/eval-after` | `evalplus_application.py` | `results/reference:/references` | `results/eval-after` |
| SWE before | `sources/swe-before` | `swe_application.py` | `native-inputs/study:/study` | `results/swe-before` |
| SWE after | `sources/swe-after` | `swe_application.py` | `native-inputs/study:/study` | `results/swe-after` |

Use the same restrictions for all five operations, with the listed source/script/result changes. Capture stdout, stderr, exit code, elapsed time and `docker inspect` for every attempt. In the original application reference preparation had a 7,200-second bound; each EvalPlus version had at most 3,600 seconds inside a 14,400-second overall reference/application bound; each SWE component run had 120 seconds. A timeout ends that attempt and preserves its partial records. Neither retries nor modified cohorts can be credited as the original fixed study.

The two EvalPlus operations together make 1,312 candidate-bank calls. The two SWE operations make 140 component entry calls and execute zero patches. The original observer scripts are preserved, including their documented coverage restrictions. New runs require new output identities and honest accounting of disagreements; do not repair a record by inserting events or archive markers.

## Interpretation

The released observations are the exact historical application. Fresh timing calibration can alter timeouts, so a fresh acquisition is a new measurement, not a bit-for-bit replacement. `canonical-reference-manifest.json` records the original calibration pickle identities; those original pickle payloads remain in the local study archive. Use saved-evidence replay to verify the exact published conclusions without executing upstream programs.
