# Minimal architecture

```text
CLI / future Agent
        |
        v
plc_tools stable contracts
        |
        v
runtime adapters (MatIEC + Docker/OpenPLC)
```

## Layers

### Agent

The Agent will receive a natural-language requirement, decide the I/O and
state model, generate ST, and run a bounded repair loop. It will only call
`plc_tools`; it will not know Docker, REST endpoints, or compiler flags.

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
