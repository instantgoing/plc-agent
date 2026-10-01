# Phase 4 progress and acceptance evidence

## Architecture

`frontend/` is one React/TypeScript/Vite application with locally bundled Monaco.
`web_ide/` is a localhost FastAPI gateway. It reuses `CodexPLCSession`,
`PLCMCPAdapter`, and `ProjectIndexer`. Runtime actions are delegated to the
existing P2 adapter. Codex stays the only Agent; the Web gateway converts its
public CLI JSON items to a small WebSocket event schema and never forwards
reasoning items. Thread IDs remain owned by Codex, with only references and
titles in `.plc-agent/web-sessions.json`.

The current Codex integration is the P1 CLI JSON stream, not a Codex App Server.
Its MCP stdio server starts per Codex turn. The gateway's direct PLC actions
reuse the same P2 adapter and never invoke MatIEC, Docker, or OpenPLC manually.

## Endpoints

- Workspace: `GET /api/workspace/tree`, `GET /api/workspace/file?path=...`,
  `PUT /api/workspace/file`, `GET /api/workspace/status`.
- PLC: context, symbol and reference reads; check, compile, status, start,
  stop, read, force, and verify. Force is refused outside simulation mode.
- Agent: message, interrupt, current and previous sessions, new and resume.
  `GET /api/agent/events?after=N` and `/ws/events?after=N` replay the in-memory
  bounded event window across browser reconnects. Sequence numbers allow the
  browser to discard duplicates.
- Changes: list and before/after source for Monaco Diff.
- Health: project, MCP adapter, Codex CLI authentication and outbound HTTPS
  reachability, and Runtime status.

The local proxy can be started on demand using `PLC_CODEX_PROXY_EXECUTABLE`
alongside `PLC_CODEX_PROXY`. Startup and each Agent request reuse a listening
proxy, or launch the explicitly configured local executable with its window
hidden and wait for the port for up to 10 seconds. Failure is reported in the
Agent panel; it does not leave the Agent busy or prevent file editing. The
gateway does not change system proxy settings or stop a shared proxy on exit.

The file API accepts only visible source/config/document extensions inside one
workspace. It rejects `..`, absolute paths, hidden control directories, and
resolved paths outside the workspace. Saving requires the version read by the
editor and returns HTTP 409 after an external change.

## Verified locally on 2026-09-25

- React production build and Vitest diagnostic/conflict tests passed.
- Gateway unit/integration tests passed: workspace tree/read/save/traversal,
  WebSocket replay, public event adapter, session resume, context query,
  change events/diff, health, and delegated runtime operations.
- Headless Chromium opened a disposable PLC workspace, edited ST in Monaco,
  used the PLC Explorer to jump to an FB, ran real MatIEC against an invalid
  assignment, displayed Problems and a Monaco error marker, jumped to the
  source, detected an external edit while the editor was dirty, and opened
  Monaco Diff. Screenshot: `artifacts/phase4/browser-editor-conflict.png`.
- Real gateway Runtime path passed on a disposable fault-interlock source:
  `plc_check`, `plc_compile`, `plc_start`, `plc_read`, `plc_force`, `plc_read`
  with `Motor = true`, `plc_verify` with `passed = true`, forced-input release,
  and `plc_stop`.
- A second headless Chromium run used the Runtime and Variables panels against
  the real test Runtime: compile/load, start, force `StartPB`, observe live
  `Motor = true`, verify the fault plan, release, and stop. Screenshot:
  `artifacts/phase4/browser-runtime.png`.
- The original P2 MCP protocol/MatIEC/Runtime tests and P3 MCP context test
  passed. The original P3 Runtime test passed when the repository's local
  MatIEC config was loaded into the invoking Python process. A direct test
  invocation without that config failed with `MatIEC executable not found`;
  it was an invocation issue, not a source regression.

## Real Agent browser acceptance on 2026-09-26

- A real Chromium browser sent a Fault interlock request to Codex on a
  disposable PLC workspace. Codex called project context, symbol and reference
  tools, patched only `Motor.st`, checked and compiled it, and verified the
  existing five-step plan on the real simulator with `passed=true`. Forced
  inputs were released and the Runtime was stopped by Codex.
- Reloading the browser while the task ran reconnected to the same backend
  task. A clean Monaco editor reloaded the Agent's change, the Changes panel
  marked the file as Agent-originated, and Monaco Diff displayed the actual
  before/after source. Screenshot: `artifacts/phase4/browser-agent-diff.png`.
- A second real turn continued the same Codex thread and added a comment while
  the browser held unsaved ST. The conflict banner appeared, unsaved text
  remained in the editor and stayed absent from disk, and View Diff compared
  the user's buffer against the Agent's disk revision. Screenshot:
  `artifacts/phase4/browser-agent-dirty-conflict.png`.
- This found and fixed a missing `--skip-git-repo-check` on resumed CLI turns.
  Public item IDs now include a per-turn prefix, preventing second-turn tools
  or messages from overwriting first-turn UI records. Nonzero CLI exits retain
  actionable stderr and infrastructure failures appear as Agent errors.
- The complete real browser test passed in 299.423 seconds. Its first turn
  established behavior correctness; its second comment-only turn requested
  only `plc_check`, so the harness correctly reported behavior unverified for
  that new revision rather than reusing old verification evidence.
- The default regression suite passed 154 tests with 24 opt-in skips. Proxy
  startup/reuse, bounded failure handling, resumed CLI arguments, and event ID
  isolation are covered. Phase 4 dependencies now explicitly include
  `websockets` so the supported virtual environment can stream events.

## Final P4 browser acceptance (2026-10-01)

- Real Codex Agent E2E A now passes: direct OpenAI requests timed out because
  the local proxy was not passed to the Codex process. With `PLC_CODEX_PROXY`
  configured, a real Codex CLI turn completed, and the Web gateway streamed
  `plc_find_symbol`, the answer, and a resumable thread. Session creation is
  now synchronized so parallel gateway requests cannot replace the active
  session. The live Agent edit/diff and dirty-conflict browser workflows now
  pass as recorded above.
- The browser opened `motor.st`, used Build & Run, and verified the unchanged
  18-step `motor.tests.json` plan on real MatIEC/OpenPLC. The motor was still
  running six seconds into the timed interval and was stopped after the total
  wait exceeded ten seconds. Verification returned `success=true`,
  `passed=true`, all 18 step results passed, and forced inputs were released.
  The test stopped the Runtime. Evidence: `artifacts/phase4/release-ten-second.json`
  and `release-ten-second.png`.
- The browser checked a disposable `broken.st` containing `Motor := ;` and
  displayed real MatIEC diagnostics. A real Codex turn called `plc_check`,
  changed only that assignment to `Motor := Start;`, then called check,
  compile, start, and verify. The unchanged three-step plan returned
  `passed=true`; Codex unforced the input and stopped the Runtime. The browser
  confirmed `state=verified`, the fixed source, and stopped Runtime. Evidence:
  `artifacts/phase4/release-codex-repair.json` and
  `release-codex-repair.png`.
- Run both repeatable scenarios serially with
  `PLC_WEB_RELEASE_ACCEPTANCE=1 python -m unittest tests.test_web_ide_release_acceptance -v`
  in an authenticated environment with Chromium, MatIEC and the OpenPLC test
  Runtime. The test refuses to replace an already running program.

Terminal has no safe PTY gateway. The P1 CLI uses `--approve-for-me`, so there
is no interactive Codex approval request to render in this integration. These
remain deferred. Trace was delivered separately in Phase 5.
