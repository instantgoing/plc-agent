# PLC-Agent development rules

## Scope

This repository is a new, cross-platform PLC-Agent. Do not read, import, or
reuse the sibling legacy PLC-Agent based on TIA Portal, Siemens Openness,
PLCSIM, or Windows GUI automation.

## Current milestone

The project is being built in milestones from M0 to M7. M0-M5 have recorded
real MatIEC/OpenPLC acceptance. Phase 1 moved the active Agent entrypoint from
smolagents to Codex and passed real Codex/MatIEC/OpenPLC acceptance on
2026-09-25. Phase 2 exposes the same PLC core through a simulator-only MCP
server. Historical M5 files remain for tests. Do not add UI, databases, RAG,
or multi-agent orchestration.

Phase 3 adds a derived, static PLC Project Context for source-level discovery.

## Architecture boundary

Keep these layers separate:

1. `agent/`: requirement understanding and the bounded repair loop.
2. `plc_tools/`: stable tool contracts such as check, compile, run, force,
   read, trace, and verify.
3. `runtime/`: Docker/OpenPLC/MatIEC implementation details.

The agent must not know Docker commands, MatIEC command-line details, or
OpenPLC REST details.

## Verification rule

Compiler success is not behavior success. Every milestone must include a real
execution or test result. Do not replace the runtime with a fake implementation
and do not claim behavior verification from compilation alone.

## Codex PLC engineering workflow

You are operating inside a PLC engineering workspace. Inspect the existing
project and its ST files before editing. Make the smallest necessary patch and
review the diff; do not rewrite unrelated PLC code or regenerate a whole file
when a local edit will do. Respect the `agent/`, `plc_tools/`, and `runtime/`
boundaries. Do not modify `plc_tools/` or `runtime/` unless the task explicitly
requires it.

When a dedicated PLC MCP tool exists, use it instead of invoking the underlying
compiler or Runtime manually through shell commands. Use `plc_check` instead
of invoking MatIEC, `plc_force` instead of Runtime endpoints, and `plc_read`
instead of inspecting Runtime internals. Do not bypass the MCP abstraction
unless debugging the MCP implementation itself. The CLI remains available for
human debugging and CI.

Before non-trivial PLC changes, inspect `plc_project_context`. Use
`plc_find_symbol` when locating PLC symbols, and `plc_find_references` before
modifying shared Function Blocks, Functions, global variables, or interfaces.
Do not assume a variable name is unique across the project. Use returned source
locations to inspect the real ST before editing. The semantic index is derived
data; source files remain the source of truth. Shell inspection remains useful
for ordinary files, Git, and follow-up reading.

After modifying ST, call `plc_check` and read its structured diagnostics.
Repair errors and check again. Call `plc_compile` when the test Runtime is
available. For behavior, start the Runtime, apply test inputs, call
`plc_verify` with a project JSON plan, and stop the Runtime. Release any forced
variables.
Compilation success does not establish behavioral correctness. Only report
behavior as verified when a real verification result has `passed: true`.

Limit repair to five check/compile attempts per turn. On exhaustion, report
the last diagnostics and changed files as incomplete. Work only with the
MatIEC simulator and test Runtime; never connect to or control a physical PLC
without a separate explicit safety policy.

Safety levels: Level 0 covers project info, check, and read; Level 1 covers
compile and future trace; Level 2 covers test Runtime start, stop, force, and
verification inputs. Level 3 physical PLC deployment, writes, and forcing are
disabled.
