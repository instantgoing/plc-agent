## Phase 5 Current State

Audit of the existing P4 implementation, before P5 changes (2026-09-26).

### Runtime Monitoring

`frontend/src/App.tsx` polled the Variables view every 750ms. It had no shared subscription union, per-value timestamp, stale detection, or force-state model.

### Variable Identity

P3 records already contained owner, scope, type, address and source location. Runtime CSV mapping retained relative instance members but stripped the program owner. Name dictionaries and frontend name deduplication could collapse different POUs.

### Force Support

P2 supported confirmed located `%I/%Q` forces and an explicit release list on the existing force contract. There was no named `plc_unforce`, shared force registry, overview, or stop-before-release lifecycle.

### Trace Support

`project_info` reported `trace=false`. The Web IDE Trace view was a deferred placeholder, rather than a stable trace tool.

### Runtime Transport

The Web IDE already had one event WebSocket. OpenPLC's native `0x44` command read an index list in one response, while each command previously created another authenticated Socket.IO polling connection and Docker inspection.

### Existing Ladder Support

No Ladder implementation existed. P3 already used Tree-sitter IEC ST; it could be reused without introducing another regex parser.

### Existing Visualization Libraries

React, Monaco, Vite and Vitest were available. No chart library existed.

### Missing Capabilities

DebugSession, stable variable IDs, runtime/source identities, Watch, confirmed force state, bounded traces, summaries, Ladder IR, live rendering, and offline/stale handling.

### Minimal P5 Architecture

PLC tool contracts own identity, observations, forces and trace compression. One Gateway DebugSession merges UI subscriptions, polls the existing batch read abstraction, and broadcasts transient `debug.values` over the existing socket. Variables/Watch/Ladder share its state; Trace uses the same channel with a separate requested cadence. Tree-sitter generates conservative backend Ladder IR. Codex keeps its harness and accesses live evidence through PLC tools.

The audit also found native OpenPLC `DEBUG_GET_MD5` and an eight-byte `IEC_TIME` ABI; implementation uses these actual Runtime contracts.
