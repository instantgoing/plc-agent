# Phase 2 PLC MCP acceptance (2026-09-25)

## Current PLC Tool Call Map (before Phase 2)

| Caller | Path | Input | Result |
| --- | --- | --- | --- |
| Codex | shell `python main.py ...` | CLI arguments | JSON on stdout, exit code |
| CLI | `plc_tools.check/compile/runtime/variables/verify` | file paths, Python values | structured dataclasses |
| `plc_tools` | `runtime.matiec` and `runtime.openplc` | internal calls | real MatIEC/OpenPLC results |

Phase 1's Codex harness counted only command-execution events. MatIEC and
OpenPLC ran in Docker on the Windows host; Python and Codex ran on Windows.
The CLI already existed. Check and compile already parsed diagnostics. Runtime,
variable, and verify functions already returned structured results, with
`tool_error` for infrastructure failures. Only the Codex-to-CLI hop depended
on shell commands and their stdout.

## Architecture

```text
Codex -> MCP stdio -> plc_tools.mcp_server -> plc_tools.mcp_adapter
                                               |
CLI main.py ----------------------------------+--> existing plc_tools core
                                                      |
                                                 runtime/ MatIEC + OpenPLC
```

The MCP server does not implement a compiler, Runtime client, variable protocol,
or verification algorithm. `plc_mcp.py` is an absolute-path launcher for Codex.
`agent/codex_client.py` passes a workspace-scoped MCP configuration for each
`main.py agent/chat` turn. Ordinary Codex sessions can use the registered `plc`
stdio server. The old CLI remains available for CI and debugging.

## Tools and schemas

| Tool | Input | Principal output | Safety |
| --- | --- | --- | --- |
| `plc_project_info` | `{}` | project root, ST files, compiler/runtime names, capabilities | 0 |
| `plc_check` | `{ "file": "path.st" }` | `success`, `diagnostics[]`, optional `error` | 0 |
| `plc_compile` | `{ "file": "path.st" }` | `success`, `artifact: null`, `diagnostics[]`, `duration_ms`, compile status | 1 |
| `plc_start` / `plc_stop` | `{}` | `success`, `state`, optional `error` | 2 |
| `plc_force` | `{ "variables": {"Start": true}, "release": [] }` | `success`, `applied`, `released`, `failures[]` | 2 |
| `plc_read` | `{ "variables": ["Motor"] }` | `success`, `values`, variable metadata, real scan tick when available | 0 |
| `plc_verify` | `{ "file": "plan.tests.json" }` | `success`, `passed`, step `results[]`, `failures[]`, cleanup result | 2 |

`plc_trace` is deferred because no stable core implementation exists. Level 3
physical PLC deploy/write/force/start/stop is disabled; the server exposes only
the MatIEC/OpenPLC test environment. Source and plan paths are confined to the
configured project root. The server emits logs to stderr, never into a tool's
structured result.

Diagnostics are individual records with severity, file, line, column, range,
source line, and `code: null` where MatIEC has no code. Compiler warnings may
coexist with `success: true`. The common `error.type` values used at the MCP
boundary are `invalid_argument`, `file_not_found`, `compiler_error`,
`runtime_not_running`, `runtime_start_failed`, `unknown_variable`,
`force_failed`, `read_failed`, `verification_failed`, and
`infrastructure_error`. A valid behavior mismatch returns `success: true,
passed: false`; tool execution and behavior outcomes remain separate.

## Real acceptance

- Independent MCP stdio client discovered all eight tools and received
  structured responses. A real Codex CLI session discovered and called
  `plc_project_info` successfully.
- Phase 2 protocol tests: 3 passed with real MatIEC/OpenPLC enabled. They
  covered valid and invalid ST, compile/start/read/stop, unknown variable,
  and a deliberately failed behavior assertion (`success: true, passed: false`).
- Existing MatIEC/OpenPLC integration tests: 5 passed. The M3 variable test
  now uses `tests/fixtures/m3_motor_follow.st`, retaining its original program
  independently of the upgraded example.
- Unit suite: 117 passed, 18 skipped after the final verify-plan validation
  hardening. Targeted post-change tests: 23 passed. CLI `check`, `compile`,
  force-release, stop, and status were run against the real test environment;
  final status was `STOPPED`.

For the end-to-end task, Codex edited `examples/motor_start_stop.st` and added
`examples/motor_start_stop.tests.json`. It called `plc_project_info`, received
real structured MatIEC errors from its first `plc_check`, repaired the ST
declaration, and passed its second check. It then called `plc_compile`,
`plc_start`, `plc_force`, `plc_read`, and `plc_verify`. Its first real verify
returned `success: true, passed: false` on the timeout assertions. Codex
inspected those failures, released inputs, stopped the Runtime, revised the
program and test timing, then passed check, compile, start, and all 17 real
verify assertions. It released Start/Stop and stopped the Runtime. The active
Codex harness returned `state: verified` and `success: true`.

The recorded shell commands in that Codex turn were limited to reading files,
searching the repository, and Git diff/status. The PLC operations above were
all `mcp_tool_call` events. No MatIEC, Docker, Runtime endpoint, or internal
Python PLC script was invoked by the Codex shell during normal PLC work.

Final verify details (all values came from the real Runtime):

| Steps | Scenario | Expected Motor | Actual Motor | Result |
| --- | --- | --- | --- | --- |
| 1-2 | Stop reset, idle | off, off | off, off | pass |
| 3-4 | Start edge, Start released | on, on | on, on | pass |
| 5-7 | Stop dominates, held Start cannot restart, rearm | off, off, off | off, off, off | pass |
| 8-11 | Fresh Start, release, extra Start edge, pre-timeout | on, on, on, on | on, on, on, on | pass |
| 12-14 | After 10-second timeout, held Start, rearm | off, off, off | off, off, off | pass |
| 15-17 | Fresh Start, immediate Stop, stopped finish | on, off, off | on, off, off | pass |

The first MatIEC check produced line/column diagnostics for function blocks
declared in the located-variable section. The first behavior plan reported
steps 11-13 with expected `Motor=false`, actual `true`; the first program and
plan did not establish the required timeout. Codex revised the
program to use an internal `Running` state and adjusted the plan's pre-timeout
and post-timeout sample points before the passing run. These failures were
reported as structured tool results, so the same Codex turn continued its
repair loop rather than treating them as protocol exceptions.

## Remaining limits

- There is no independent persistent compilation artifact; `artifact` is
  `null`, while generated file names and Runtime compile status are preserved.
- The existing Runtime debug read can intermittently return an incomplete
  payload; MCP reports this as `read_failed`. The end-to-end run saw one such
  read while debugging, then subsequent real reads and verification passed.
- Codex CLI network requests were slow and retried before tool use, although
  the MCP server itself connected and completed calls.
- This workspace's execution sandbox failed to initialize when a local
  `.codex/` directory was created. The file was removed; Codex integration
  uses the registered user-level server for ordinary sessions and explicit
  per-turn MCP settings for `main.py agent/chat`.
- `plc_trace` and a project graph remain outside Phase 2. A later phase can
  add semantic project discovery and a bounded trace primitive after a stable
  core implementation exists.
