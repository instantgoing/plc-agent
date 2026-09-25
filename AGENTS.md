# PLC-Agent development rules

## Scope

This repository is a new, cross-platform PLC-Agent. Do not read, import, or
reuse the sibling legacy PLC-Agent based on TIA Portal, Siemens Openness,
PLCSIM, or Windows GUI automation.

## Current milestone

The project is being built in milestones from M0 to M7. M0-M5 have recorded
real MatIEC/OpenPLC acceptance. Phase 1 moved the active Agent entrypoint from
smolagents to Codex while retaining the existing PLC tools, and passed real
Codex/MatIEC/OpenPLC acceptance on 2026-09-25. Historical M5 files remain for
tests. Do not add UI, databases, RAG, multi-agent orchestration, or begin
Phase 2 without an explicit request.

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

After modifying ST, run the existing `main.py check <file.st>` CLI and read its
structured diagnostics. Repair errors and run check again. Compile with
`main.py compile <file.st>` when the test Runtime is available. If behavior can
be tested, start the Runtime, apply test inputs, use `main.py verify <plan.json>`
to compare real outputs, and stop the Runtime. Release any forced variables.
Compilation success does not establish behavioral correctness. Only report
behavior as verified when a real verification result has `passed: true`.

Limit repair to five check/compile attempts per turn. On exhaustion, report
the last diagnostics and changed files as incomplete. Work only with the
MatIEC simulator and test Runtime; never connect to or control a physical PLC
without a separate explicit safety policy.
