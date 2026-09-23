# Bounded native telemetry: protocol 1

This release implements R11 A4 as an acquisition component. The existing five replay commands remain unchanged. The explicit Python API is `zerorun_harness.telemetry.capture_native`. It starts native processes; use the documented isolated container for untrusted native/candidate code. It is not a security sandbox or an arbitrary-source binding generator.

## Qualified runtime and operation

Native acquisition is supported only on Linux CPython **3.11.16**, multiprocessing **fork**, optimize **0**. Other interpreter/runtime/start-method combinations return `UNSUPPORTED` before adapter execution. Replay and portable protocol tests remain supported on the package's other declared Python versions. A broader runtime needs separately recorded qualification and a new release.

```python
from zerorun_harness.telemetry import capture_native
result = capture_native(
    "/readonly/qualified_adapter.py", adapter_sha256, primitive_argument,
    start_method="fork", wall_seconds=10, max_trace_bytes=16 * 1024 * 1024,
)
```

The trusted, source-pinned adapter provides `run(emitter, argument)`. It exposes already observed primitive native facts through `emitter.emit(fact)` and returns a bounded primitive native value. It must not use emitter success/failure to change native evaluator policy. Domain bindings and semantic coverage require separate qualification; adapter hashes establish bytes, not correctness. The adapter is at most 1 MiB, verified before invocation and again in the supervisor, then compiled from those verified bytes.

Every call starts a fresh supervisor interpreter in Python isolated mode and a new process group. The supervisor creates the side channel and independent native-result shared memory before forking one producer. The producer closes its read descriptor and initializes the emitter, serializer dependencies and stored write function **before importing or invoking the adapter**, so native reliability guards do not need to reopen the telemetry descriptor or import telemetry dependencies. Native stdout/stderr are inherited unchanged and never serve as the side channel.

The supervisor drains concurrently while the producer runs. The native return/exception outcome travels through separate caller-owned primitive shared storage. A native timeout, `KeyboardInterrupt` or `SystemExit` remains a native process outcome. On the declared wall deadline, the supervisor terminates the worker and records incompletion. The outer API also has a supervisor deadline and kills its process group on failure. There is no zero-overhead claim; wall durations and any timeout outcomes are retained.

## Exact transport parameters

| Property | Frozen protocol-1 rule |
|---|---|
| Descriptor route | Dedicated Linux `os.pipe2(O_NONBLOCK | O_CLOEXEC)` descriptors inherited by `fork`; one producer; read descriptor closed in producer and write descriptor closed in supervisor |
| Setup requirement | Nonblocking writer and `PC_PIPE_BUF >= 4096`; unavailable setup is `UNSUPPORTED` |
| Atomic frame | At most **4,096 bytes**, one `os.write` per frame |
| Header | Magic `ZR11`, unsigned big-endian 32-bit payload length, unsigned big-endian CRC32; 12-byte header |
| Payload | UTF-8 JSON; protocol ID, producer PID, packet kind; event attempt sequence allocated before serialization/write |
| Primitive grammar | Exact dict/list/str/int/float/bool/null; depth at most 8; at most 4,096 visited nodes; dict at most 32 entries; list at most 64 elements; strings at most 1,024 characters; integers at most 128 bits; finite floats; no cycles or surrogate strings |
| Trace storage | Default/hard maximum **16,777,216 wire bytes**; caller may lower to at least 4,096. On a cap, discard later data while continuing to drain, with explicit loss. Decoded-object memory adds finite representation overhead. |
| Producer seal | Attempted, emitted, dropped, primitive-rejected and partial-write counts; exactly one seal after all events |
| Collector checks | PID/protocol/type, checksum, framing, typed contiguous sequence, exact seal grammar/counts, and separate control-plane counters |
| Partial/malformed frame | Invalidate the dependent trace; never scan ahead to reinterpret trailing bytes as a new valid stream |
| Missing seal or packet after seal | Incomplete transport; no absence-based native accusation |
| Wall bound | Positive, at most 60 seconds per adapter; caller-selected and retained |

CRC32 detects accidental wire corruption; neither it nor SHA256 authenticates an adversarial producer. Cooperative qualified adapters remain an assumption. Unknown producers, duplicate events, sequence gaps, malformed or duplicate JSON keys and inconsistent seals invalidate transport.

The emitter handles only its own `PrimitiveError` and transport `OSError` values with errno **EAGAIN/EWOULDBLOCK, EPIPE, EBADF, EINVAL**. It records loss and returns without modifying native objects or branching policy. Partial writes are recorded as loss. It does **not** catch generic native exceptions, `TimeoutError`/ETIMEDOUT, EINTR, `KeyboardInterrupt` or `SystemExit`. Descriptor initialization errors occur before native code and are classified unsupported. No candidate `repr`, `str`, pickle hook or implicit container conversion is used to serialize observations. Native exception class names are retained without formatting their potentially custom messages.

## Health and qualification

Receipts separately report `native_complete`, `transport_intact` and `semantic_coverage`. The last is deliberately **null** at this layer: an intact seal is not proof that every required semantic callback existed. A silently absent callback cannot gain semantic qualification from an empty intact channel. Domain consumers must obtain coverage qualification separately; the existing relationship checker rejects missing/non-true required health premises.

`CAPTURED` means native completion and intact bounded transport. `INCOMPLETE` records a native/transport failure or missing premise. Neither is candidate acceptance or a claim of evaluator correctness. `UNSUPPORTED` denotes an unqualified runtime/start method or unavailable descriptor setup. Native return data, process exit, timeouts, event/seal inventories, loss reasons, implementation hashes, adapter identity and separate supervisor/producer IDs remain visible.

## Executed qualification

The retained suite exercises independent wire encodings, checksum corruption, sequences, seals, oversized/malformed primitives, no-repr/no-pickle behavior, descriptor modes, limits and exception propagation. The physical Linux campaign covers normal transmission, the unmodified pinned EvalPlus reliability guard, native stdout/stderr, a closed writer, missing seal, partial/corrupt frames, malformed and silent callbacks, trace-cap loss, native timeout/termination/interrupt, wall deadline, timing control, stopped collector and broken channel. Expected native sentinels and wire values are specified separately from production collector output.

The real guard baseline imports only the pinned native utility, not the observer, mapper or checker. Its byte identity and results are retained. These are exposed transport/component qualification controls, not new benchmark candidates, unfamiliar semantic challenges, independent users or a guarantee of arbitrary observer fidelity. This release does not retroactively replace the S2 acquisition observer or its original results.
