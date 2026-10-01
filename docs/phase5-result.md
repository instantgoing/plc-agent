## Phase 5 Result

Phase 5 adds simulator online observability to the P4 Web IDE. Real MatIEC/OpenPLC behavior verification returned `passed=true`; real Chromium and Codex debugger acceptance passed. Production build, frontend tests and the P1-P4 regression suite passed. No physical PLC, Ladder editing, process simulation or multi-agent orchestration was added.

### Architecture Before

P4 Variables had an independent 750ms browser read loop and simple-name identity. Trace was a placeholder. There was no shared debug state, runtime program identity or Ladder.

### Architecture After

`plc_tools` owns stable observations/forces/traces, `runtime` owns native OpenPLC transport, and one `web_ide.DebugSession` owns subscription union and scheduling. Watch, Variables and Ladder consume one external React store fed by the existing event socket. Trace samples travel through that same monitor. Static Ladder/context and live values remain separate.

### Debug Session

Centralized subscriptions, deduplicated batch reads, timestamps, last update, stale/offline/unresolved states, runtime and source change detection, trace interruption, and build reset. Requested refresh choices are 100/250/500/1000ms. The scheduler does not overlap reads or pretend that the Runtime meets a cadence faster than actual transport latency.

### Variable Identity

IEC identifiers are case-insensitive; IDs are canonical lowercase `owner:name`, e.g. `main:motor`, `main.motor1:running`, `main.motor2:running`. Program-instance paths are retained when multiple instances of one program exist. Ambiguous simple names are refused. P3 symbol/reference queries resolve canonical IDs back to source declarations. Source records and runtime map entries remain distinct.

### Watch System

P3-backed symbol/address search with explicit selection; add/remove, pin, clear, live values and source navigation. Workspace localStorage persists only exact variable IDs. Removed IDs remain unresolved and are never redirected to a same-name symbol. Runtime values are not persisted in Watch storage.

### Force / Unforce

Confirmed BOOL or numeric located I/O forces, right-click actions, explicit MCP/CLI/HTTP Unforce, visible FORCED state, and tool-observed Force Overview/Unforce All. Only confirmed operations change the registry. Compilation and stop release known forces before replacing/stopping a program; failures remain explicit. Physical-force mode is refused by the core. Unforce All covers tool-observed forces, not unobservable external forces.

### Runtime Transport

One IDE event WebSocket. `debug.values` is transient and is not put into Agent replay history. A reconnect receives a current snapshot; browser socket loss disables values and highlighter. Native batch debug reads reuse an authenticated Socket.IO polling session. Cross-process OS locks serialize build/start/stop/read/force operations and release automatically after process termination.

### Trace Engine

Backend monotonic relative times plus wall timestamps, typed signals, build identity, start/pause/stop/clear, interruption on unavailable signals or build change, and a maximum 10,000-sample ring. Normal runs remain temporary; test evidence and explicit exports are the only trace files written.

### Trace Visualization

uPlot provides separate digital lanes for BOOL, numeric/TIME curves, drag zoom, cursor, reset zoom, and JSON/CSV export. TIME debug units are milliseconds. No BOOL interpolation is used. The Debugger subtree updates without sending each sample into the editor/Agent application state. Visual QA caught and fixed a resize feedback loop and dock clipping.

### Trace Summary

Deterministic BOOL transitions (bounded output and full transition count) and numeric min/max/start/end. Codex receives the summary as runtime context; `plc_trace(action="summary")` or `action="range"` can retrieve the selected temporary IDE trace through a localhost, workspace-bound gateway. A standalone MCP trace retains its own bounded recording for summary/range queries.

### Program Identity

Build UUID, normalized source SHA-256, source file, loaded time and native Runtime MD5. Each actual read/force validates the native program hash before using debug indices. Compilation failure during upload invalidates the debug map; a concurrent source change also prevents publishing misleading metadata.

### Source / Runtime Consistency

Source edits show SOURCE CHANGED / SOURCE MODIFIED and disable live highlighting. Unknown or foreign build identities also disable highlighting. Build & Run publishes a fresh identity, resets observations/trace, refreshes symbols and preserves exact Watch IDs. Runtime hash mismatches refuse reads and writes rather than using old indices.

### Ladder IR

Backend Tree-sitter AST produces structured logic and outputs with file/line/symbol/variable ID mapping. React consumes IR and never parses ST. Results are `supported`, `partial` or `unsupported`. Negated branches use De Morgan topology rather than an incorrect graphical negation.

### Supported Ladder Constructs

BOOL assignment, series AND, parallel OR, NOT contacts/branches, latch expressions, basic scalar comparisons, concrete FB-instance BOOL assignments, and TON/TOF calls with BOOL IN and literal PT. Timer Q/ET are actual runtime observations.

### Unsupported Ladder Constructs

IF/FOR and other control-flow structures, arithmetic/non-BOOL assignments, unsupported member/type expressions, arbitrary FB invocation wiring, and syntax errors use explicit source fallback. CTU is not implemented. This visualization cannot be recompiled or edited as Ladder.

### Live Ladder

Actual contacts/coils, forced indicators, timer Q/ET and source clicks are available. Unknown/stale/offline/mismatched data never stays green. Contact/coil states are sampled observations; this is not a scan instruction execution trace.

### Agent Debug Integration

The existing Codex harness now requires observations before behavior diagnosis, and shared absolute state configuration keeps its MCP process aligned with the IDE build. Real acceptance called symbol/reference tools and one stable-ID batch read. Codex reported Start=TRUE, Stop=FALSE, Fault=TRUE, Motor=FALSE and identified the Fault interlock; it explicitly did not guess unobserved timer state.

### Files Added

- `plc_tools/debug.py`, `plc_context/ladder.py`, `web_ide/debug_session.py`.
- `frontend/src/Debugger.tsx`, `debugStore.ts`, `LiveLadder.tsx`, `TracePlot.tsx`, `ForceMenu.tsx`, debugger styles and store tests.
- `tests/test_online_debugger.py`, `test_online_debugger_live.py`, `test_online_debugger_polish.py`, `test_online_debugger_mcp_live.py`, Motor/Timer/same-name/100-variable fixture and behavior plan.
- Phase 5 audit, this report, and explicit acceptance artifacts under `artifacts/phase5/`.

### Files Modified

- PLC state, variables, compile, runtime, adapter, MCP server and exports; native Runtime transport.
- P3 indexer; Codex instructions/client configuration; CLI commands.
- Gateway service/app/entrypoint; App integration and frontend package/lock files.
- MCP discovery tests and compile contracts (including isolated test state to prevent interference with a live build).

Pre-existing P4 uncommitted work was preserved. No commit was created.

### Unit Tests

Default Python suite: **183 tests, 27 opt-in skips, no failures**. Frontend: **6 tests passed**. Meaningful coverage includes identity ambiguity/instances, batch deduplication, unsupported types, force acknowledgement/rejection, native hash mismatch, physical-force refusal, source changes, ring/summary/edges, timer codecs, Ladder topology/fallback/source mapping, subscriptions, stale/offline, WebSocket freshness, selected trace workspace binding, release-before-stop/upload, and idempotent stop. Compiler contract tests now use temporary state files.

### Integration Tests

Real Runtime verified Start/Motor behavior, five-second TON Q/ET, FB Motor1/Motor2 isolation, numeric reads, force tracking/release and the JSON behavior plan (`passed=true`). Actual connection to an unavailable Runtime endpoint interrupted tracing and marked observations unavailable. Stop cleanup was retested successfully, with no forces remaining.

### E2E Tests

Real Chromium/Codex workflow passed in **173.626s**: Watch/search/persistence, force/unforce/overview, live Ladder/source click, Trace, source mismatch warning, Build & Run and stale/offline UI. Additional real browser polish acceptance checks timer values, plot visibility/viewport width, right-click force and automatic release before stop. Evidence: `acceptance.json`, `polish-acceptance.json`, `real-trace.json`, `agent-debug-events.json`, `live-ladder.png`, `trace-timeline.png`, `source-runtime-mismatch.png`.

The earlier acceptance artifact records a cleanup failure after stopping first. The implementation now releases known forces before stopping; the polish test confirmed release with an empty force registry. A redundant stop exposed another native error, fixed by making runtime commands idempotent. Final fresh-process MCP acceptance (`mcp-acceptance.json`) exercised canonical references, batch snapshots, explicit Unforce, real Trace record/summary/range, and verification (`passed=true`), then confirmed two consecutive Stop calls succeed with Runtime stopped and no known forces remaining.

### Performance

Measured on this Windows host using the real Runtime, eight polls per size with 250ms pauses; timings include periodic runtime status checks. Host Python CPU excludes Docker/Runtime CPU and is not system-wide CPU utilization.

| Variables | Mean poll | Maximum poll | Host Python CPU |
|---|---:|---:|---:|
| 10 | 286.4ms | 574.0ms | 9.0% |
| 50 | 350.6ms | 573.4ms | 12.3% |
| 100 | 368.5ms | 630.8ms | 16.3% |

The 100-variable browser observation windows reported no >50ms long tasks. Monaco DOM mutations were measured in the first run but do not establish React commit count: Monaco has its own rendering/animations. Debug updates enter a child external store, not the root App. These are short local measurements, not an eight-hour soak test.

### Known Limitations

Only the MatIEC/OpenPLC simulator is supported. Force is restricted to supported located `%I/%Q` variables. STRING and unverified types remain unavailable. Requested 100ms sampling is a target; actual transport timestamps determine the trace. Ladder covers a conservative subset and sampled states. Pause retains the trace; starting again begins a new session. Force Overview cannot enumerate forces made outside these PLC tools. Multi-file compilation and general dynamic FB wiring remain outside the existing single-ST build contract.

### Technical Debt

Native Runtime debug transport still uses Socket.IO HTTP polling. Runtime status/authentication adds latency; a persistent native WebSocket adapter and a longer soak test are useful follow-ups. The existing Monaco bundle still exceeds Vite's 500kB advisory threshold. Broader timer/counter and vendor-specific constructs require separate real acceptance, not optimistic support flags.

### Recommended Phase 6

Define the next scope separately. Useful candidates are runtime transport performance, richer typed observations and more conservative logic constructs, with longer acceptance runs. Phase 6 has not been started.

## Running

Build the frontend with `npm run build` in `frontend`, then use `python main.py web --workspace <PLC-project>`. Compile/Build & Run the project before adding supported symbols to Watch. The new MCP tools appear after restarting the MCP server; `plc_read` is already the batch debug snapshot, so there is no duplicate `plc_debug_snapshot` tool.

Opt-in real tests (run serially, since the test Runtime is shared):

```powershell
$env:PLC_DEBUGGER_LIVE='1'
$env:PLC_DEBUGGER_AGENT='1'
python -m unittest tests.test_online_debugger_live -v
# Optional visual/transport retest of that already loaded build:
$env:PLC_DEBUGGER_POLISH='1'
python -m unittest tests.test_online_debugger_polish -v
# Fresh MCP tools, reusing the already loaded build:
$env:PLC_DEBUGGER_MCP_LIVE='1'
python -m unittest tests.test_online_debugger_mcp_live -v
```
