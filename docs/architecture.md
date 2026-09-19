# Minimal architecture

```text
CLI / M5 Agent
        |
        v
plc_tools stable contracts
        |
        v
runtime adapters (MatIEC + Docker/OpenPLC)
```

## Layers

### Agent

The M5 Agent receives a natural-language requirement, uses the vendored
`smolagents.ToolCallingAgent` variant to submit complete ST plus a behavior
plan, and runs a bounded repair loop. It exposes only a serial candidate
evaluation tool to the model. It only calls `plc_tools`; it does not know
Docker, REST endpoints, Socket.IO, or compiler flags, and it cannot execute
arbitrary Python or shell code.

### PLC Tools

The public contracts are:

- `plc_check(st)`: syntax/type/symbol diagnostics.
- `plc_compile(st)`: C/runtime artifact generation.
- `plc_start()` / `plc_stop()`.
- `plc_force_variables(values)` / `plc_read_variables(names)`.
- `plc_trace(names, duration)`.
- `plc_verify(plan)`: behavior assertions.

M1 implements the first contract against a real MatIEC executable. M2 adds
`plc_compile`, `plc_start`, `plc_stop`, and runtime status against a real,
pinned OpenPLC container. The process/REST adapters live in `runtime/`, so
Docker commands, generated package paths, authentication, and endpoint details
do not leak through public results. M3 adds `plc_force_variables` and
`plc_read_variables`; M4 adds `plc_verify`. The latter three use persisted
MatIEC debug indices but keep Socket.IO and the binary 0x42/0x44 wire protocol
inside the Runtime adapter.

### Runtime

The selected runtime backend uses the MatIEC-compatible OpenPLC commit
documented in [research.md](research.md). `Dockerfile.m1` remains the small
compiler-only image. `Dockerfile.m2` layers MatIEC and xml2st over the pinned
OpenPLC base and was verified through upload, Runtime GCC/link, and a stable
`RUNNING` scan cycle.

## Correctness boundary

`plc_check` / `plc_compile` provide compiler verification only. A successful
compile never implies that outputs behave correctly. `plc_verify` executes the
program, changes inputs, waits for real scans, observes outputs, reports
expected versus actual values, and releases forces after every plan.

M5 accepts a candidate only after the same pipeline has passed real MatIEC
checking, Runtime compilation, Runtime startup, and `plc_verify` behavior
assertions. The candidate evaluation count is bounded (three by default), and
the runtime is stopped in cleanup after each candidate evaluation.
