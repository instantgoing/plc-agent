# M0 research: MatIEC and OpenPLC compatibility

Date: 2026-09-08

## Scope

This is a fresh project. The research intentionally covers the public
SemaPLC, MatIEC, and OpenPLC repositories only; it does not inspect or reuse
the sibling legacy PLC-Agent.

## Findings

### SemaPLC is the primary reference

SemaPLC's `sema-plc-tools` is already a separated PLC tool layer. Its README
documents the complete boundary we need: syntax check, MatIEC compile, upload,
start, read/force/trace variables, and behavior verification. It exposes both a
CLI and an MCP server, which confirms that the stable tool contracts should sit
between an agent and the runtime.

Reference:

- https://github.com/midea-ai/SemaPLC/tree/main/sema-plc-tools
- https://github.com/midea-ai/SemaPLC/blob/main/sema-plc-tools/src/types.ts

### MatIEC invocation

MatIEC provides `iec2c` and `iec2iec`. `iec2c` accepts textual IEC languages
including Structured Text, performs lexical/syntax/semantic analysis, and
generates ANSI C. GCC is a separate later stage; it is not part of MatIEC.

Reference: https://github.com/beremiz/matiec

The real v4 diagnostic range format is
`file:line-col..line-col: severity: message` (with an alternate colon/dash
form in older builds). SemaPLC preserves the start/end range and source line;
M1 follows the same useful subset rather than treating every stdout line as a
warning.

Reference: https://github.com/midea-ai/SemaPLC/blob/main/sema-plc-tools/src/compiler.ts

The first local tool therefore invokes `iec2c` as an external process, captures
stdout/stderr and exit status, and converts diagnostics into a stable JSON-like
result. It does not parse ST or pretend to compile it in Python.

### OpenPLC compatibility decision

SemaPLC's `build-matiec-base.sh` pins OpenPLC Runtime to:

```text
f1a70e91e4d633db3653d1097f9d42e487970a6d
```

The script explains that the current upstream main/latest moved to STruC++ and
rejects MatIEC-era generated files such as `Config0.c` and `glueVars.c`. The
pin is therefore part of the runtime contract, not an incidental version.

SemaPLC separately installs MatIEC `v4.0.11` and its IEC library into the
development image. Its runtime is forced to `linux/amd64` because the cited
MatIEC release's arm64 packaging is not reliable.

References:

- https://github.com/midea-ai/SemaPLC/blob/main/sema-plc-tools/runtime/scripts/build-matiec-base.sh
- https://github.com/midea-ai/SemaPLC/blob/main/sema-plc-tools/runtime/Dockerfile.plc-dev
- https://github.com/midea-ai/SemaPLC/blob/main/sema-plc-tools/runtime/docker-compose.yml

### Runtime interaction model

The reference tool layer uses the OpenPLC Runtime REST API for upload/start,
variable reads, and force/release operations. Verification must observe a
downstream stable condition when testing a one-scan edge; a separate
force-then-read round trip can miss a transient. This is why the eventual
`plc_verify` contract must support waiting for a condition and releasing forced
inputs after a case.

Reference: https://raw.githubusercontent.com/midea-ai/SemaPLC/main/sema-plc-tools/src/tools/verifyBehavior.ts

OpenPLC Runtime v4's current compilation documentation describes a different
modern flow and is useful for understanding upstream changes, but it is not
yet selected as this project's MatIEC backend:

https://github.com/Autonomy-Logic/openplc-runtime/blob/main/docs/COMPILATION_FLOW.md

## Reuse decision

Decision: **B — extract the contracts and compatibility facts from
`sema-plc-tools`, then implement a smaller Python tool layer.**

Reasons:

1. Directly copying the full TypeScript/MCP package would bring in UI-oriented
   scope and a larger dependency surface before M1.
2. Reimplementing the compiler or runtime would duplicate mature code.
3. A small Python process boundary preserves the useful architecture while
   allowing a later Docker/OpenPLC backend to replace local command execution.

The first extracted contract is `plc_check`: ST in, structured compiler result
out. M2 will add compile/upload/start against the pinned Runtime; M3-M4 will
add variables, trace, and behavior verification.

## M0 acceptance criteria

- SemaPLC's tool boundary inspected: pass.
- MatIEC's `iec2c` role identified: pass.
- OpenPLC MatIEC-era compatibility pin recorded: pass.
- Reuse decision recorded: pass.
- Minimal project architecture written: pass.
- M1 real compiler smoke test: pass. On 2026-09-09 the official MatIEC v4.0.11
  Linux x64 release was executed through Ubuntu WSL. `examples/minimal.st`
  returned exit 0; `examples/invalid.st` returned exit 1 with a structured
  diagnostic at line 6, columns 9-11. This is compiler verification, not
  behavior verification.
- The verified v4.0.11 Linux x64 archive is pinned in `Dockerfile.m1` by
  SHA-256 `6f1d99dd0846a2243f130d70a1d0393cf884bb7a747022d6ef14ac9f5312bd0c`.
