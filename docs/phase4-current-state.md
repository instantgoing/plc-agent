# Phase 4 Current State

### Existing Frontend
`ui/` contains no application. There is no React/Vite project or browser editor.

### Existing Backend
The active implementation is Python. `main.py` is the CLI entrypoint; `agent/` owns Codex task policy, `plc_tools/` owns PLC contracts, and `runtime/` owns MatIEC/OpenPLC details. There is no HTTP or WebSocket server.

### Codex Interface
`agent.codex_client.CodexClient` launches `codex exec --json` as a process. `CodexPLCSession` persists its thread ID in `<workspace>/.plc-agent/codex-session.json` and resumes it on the next turn. The CLI is the current main entrypoint. This is a CLI JSON event stream, not an existing Codex App Server connection.

### Streaming Capability
`CodexClient.run(on_event=...)` emits JSON events as they arrive. `CodexPLCSession.run(on_event=...)` forwards them. No WebSocket transport, replay, or browser event schema exists yet.

### Workspace API
None. Codex currently edits the workspace through its own process. The MCP adapter validates PLC file paths, but no browser file tree, read, or save API exists.

### PLC Runtime Interface
`plc_tools.mcp_adapter.PLCMCPAdapter` exposes check, compile, start, stop, force, read, and verify through the Phase 2 stdio MCP server. `plc_tools.get_plc_status` provides status. These reach the MatIEC/OpenPLC test runtime; there is no physical PLC support. `plc_trace` is not stable.

### Project Context Interface
The Phase 3 `ProjectIndexer` is held by `PLCMCPAdapter`. `project_context`, `find_symbol`, and `find_references` return derived source locations. The index is a cache of ST source, not an alternate source of truth.

### Reusable Components
Codex session and live event callback, MCP tool contracts, Phase 3 index, structured compiler diagnostics, and runtime variable map.

### Missing Components
Web gateway; secure workspace API; browser event adapter and replay; React shell and editor; diagnostics, PLC explorer, runtime, variables, and diff panels; browser session state and conflict handling.

### Minimal P4 Architecture
One localhost FastAPI gateway serves workspace and PLC APIs plus an event WebSocket. It retains the existing Codex session and P2/P3 adapters; React/TypeScript/Vite/Monaco consumes only gateway endpoints. Windows hosts browser, Node, Python, Codex, and the gateway. The current `.env.local` config uses the existing MatIEC Docker image and OpenPLC Docker test runtime. WSL Ubuntu is installed but has no configured `iec2c`, so it does not currently run the PLC toolchain. The gateway does not issue Docker, MatIEC, or OpenPLC commands.
