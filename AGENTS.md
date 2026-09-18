# PLC-Agent development rules

## Scope

This repository is a new, cross-platform PLC-Agent. Do not read, import, or
reuse the sibling legacy PLC-Agent based on TIA Portal, Siemens Openness,
PLCSIM, or Windows GUI automation.

## Current milestone

The project is being built in milestones from M0 to M7. M0-M4 are complete and
verified against real MatIEC/OpenPLC execution. The current target is M5: add a
minimal single-Agent bounded repair loop backed by a real LLM. Do not claim M5
from a mocked model, and do not add UI, databases, RAG, or multi-agent
orchestration before the relevant milestone.

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
