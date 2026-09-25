# Minimal architecture

```text
CLI / Codex harness
        |
        v
plc_tools stable contracts
        |
        v
runtime adapters (MatIEC + Docker/OpenPLC)
```

## Layers

### Agent

The active `main.py agent` and `main.py chat` entrypoints use `CodexPLCSession`
and the external Codex CLI. Codex owns the thread, file edits, and shell
execution; it calls the existing `main.py` PLC commands. The workspace stores
only the Codex thread ID and project paths. The previous M5 implementation
described below remains available to legacy tests during Phase 1 acceptance.

The M5 Agent receives a natural-language requirement and first records a
transient `RequirementSpec`. Open questions stop before candidate generation;
ready requirements proceed through `validate_candidate` and then
`evaluate_candidate`. Validation performs the real ST check without touching
Runtime. Evaluation accepts only the exact preflight-approved ST/plan pair and
is the only route to PLC success. Separate Agent-action and Runtime-attempt
budgets keep format and syntax repair from consuming real execution attempts.
The Agent only calls `plc_tools`; it does not know Docker, REST endpoints,
Socket.IO, or compiler flags, and it cannot execute arbitrary Python or shell
code.

P2's in-process `PLCSession` creates a fresh bounded Agent run per user turn.
It carries a controlled summary, the last verified ST/plan, requirement state,
and real verification evidence into a resume prompt; it does not append full
chat transcripts indefinitely. `PLCEvent` callbacks report tool progress
without coupling the Agent to any UI. A cooperative cancel signal reaches
verification; forced inputs are released before Runtime stop is reported.

P3 performs a real-model capability probe with the Agent's actual tool schemas
before the bounded run. The probe cannot call PLC tools or start Runtime.
OpenAI-compatible requests use automatic tool selection without disabling
provider reasoning. The host still requires a structured tool action for PLC
state changes and still accepts success only from real behavior verification.

P4's terminal `chat` command is a presentation layer over `PLCSession`; it
does not call Docker or Runtime directly. A worker runs each turn so Ctrl+C
can request cooperative cancellation and wait for cleanup. The one-shot JSON
`agent` command is preserved. P5's `SessionMetrics` counts events and turn
outcomes in memory, without storing full transcripts or adding persistence.

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

M5 accepts a candidate only after `validate_candidate` passes real MatIEC
checking and the same exact candidate passes Runtime compilation, Runtime
startup, and `plc_verify` behavior assertions. The Runtime evaluation count is
bounded (three by default), and the runtime is stopped in cleanup after each
candidate evaluation.
