# Original pytest phase and terminal-storage controls

This directory supplies ten authored test nodes with 28 expected native phase
reports per execution. It exercises ordinary pass/failure, skip, expected failure,
unexpected pass, setup and teardown errors, two parameter identities, and one
node with both setup and teardown errors. Repeating the suite supplies a separate
acquisition attempt, not an upstream retry or a benchmark patch result.

The original installed pytest version is exactly 8.4.2. `prepare.py` records its
complete `_pytest` and `pytest` Python source inventories before execution.
`native.py` verifies those bytes, ignores stale native bytecode, and keeps the
integrity loader active during lazy imports. External plugins and ambient
`PYTEST_ADDOPTS` are disabled. Third-party dependency/image identities remain
separate recorded inputs.

The independent `NativeReference` uses pytest's actual public
`pytest_runtest_logreport` hook. It retains exact native `TestReport` node ID,
phase, outcome, expected-failure metadata and every repeated occurrence. It has
no production observer, mapper, policy interpreter or verdict import.

`declarations.py` separately defines five source-bound native sites: produced
report, report hook input, native terminal category decision, statistics input,
and the actual stored destination `TerminalReporter.stats[category][-1]`.
Nineteen finite C1/C2 relationships cover the declared handoffs. Grammar 1.4.0
and exact registered `TestReport`/`TerminalReporter` storage are required.
The loader installs the unmangled `__zr_observe__` callback name.

For a standalone raw acquisition, in a fresh environment with pytest 8.4.2:

```sh
python validation/pytest_native/prepare.py --output /new/pytest-fixture
python -I /new/pytest-fixture/entry.py \
  --source-manifest /new/pytest-fixture/native-source.json \
  --work /new/pytest-fixture --reference /new/pytest-reference.jsonl \
  --run authored-run --attempt 1
```

Exit status 1 is expected because the fixed input deliberately includes native
failures. It is not a qualification verdict. This entry collects raw native
facts; the `swe_pytest` integration campaign separately verifies the frozen
fixture inventory, original/observed preservation, all site witnesses and
terminal-to-parser artifact provenance.

The integration preserves real stdout and stderr separately. Its SWE marker
wrapper is a separately identified acquisition artifact around the unedited
stdout bytes; it does not claim pytest emitted SWE's marker lines. A flattened
SWE map cannot automatically identify setup versus teardown when more than one
native origin remains possible. That ambiguity is retained explicitly alongside
the actual original grader result.
