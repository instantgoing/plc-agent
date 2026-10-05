# Local release validation (2026-10-02)

## Scope

This validates the simulator-only Phase 4 Web IDE and Phase 5 debugger release.
The active Codex path is separate from the historical M5 `smolagents` tests.
No physical PLC was connected.

## Working-checkout acceptance

- Real Chromium used Build & Run and verified the unchanged 18-step, ten-second
  motor plan on MatIEC/OpenPLC: `success=true`, `passed=true`, 18 passing steps,
  and successful forced-input cleanup. The before/after timeout observations
  are in `artifacts/phase4/release-ten-second.json`.
- Real Chromium displayed a MatIEC diagnostic for `Motor := ;`. A real Codex
  turn fixed only that assignment, rechecked, compiled, started, verified an
  unchanged three-step plan (`passed=true`), unforced, and stopped the test
  Runtime. See `artifacts/phase4/release-codex-repair.json`.
- The default Python suite ran 185 tests: 156 passed, 29 opt-in integration
  tests skipped, and no failures.
  The frontend passed 6 tests and built for production. Phase 5's earlier
  Chromium, MCP, and real Runtime evidence is documented in
  `docs/phase5-result.md`.

## Independent checkout

An independent clone of implementation commit `fccd099` was created without
copying its virtual environment, `node_modules`, or frontend build. A new
Python virtual environment installed `requirements-phase4.txt`; `npm ci`
installed the frontend lockfile, and both `npm test` and `npm run build` passed.
The clone started its production Web IDE and received `connection.ready` over
WebSocket. With a separate disposable OpenPLC container, the clone returned
`check=true`, `compile=true`, `verification_passed=true` for all five fault
interlock steps, `force_cleanup=true`, and final Runtime state `stopped`.
The shared test Runtime was left untouched because it already had a running
program of unknown ownership.

Commit `22f4b3f` added the missing `.gitmodules` metadata. A fresh
`git clone --recurse-submodules` resolved the pinned historical `smolagents`
commit `30bb116` and had a clean Git status. Its default Python suite again ran
185 tests: 156 passed, 29 skipped, and no failures.

## Reproduction notes

Clone with `--recurse-submodules` for historical M5 tests. The active Web IDE
does not import `smolagents`. Install Python dependencies from
`requirements.txt` (the former `requirements-phase4.txt` dependency set),
install frontend dependencies with `npm ci`, and
build the frontend before `python main.py web --workspace <PLC-project>`.
Real Runtime acceptance requires the pinned MatIEC/OpenPLC test environment;
compiler success alone is not a behavior result. The opt-in browser scenarios
run serially with `PLC_WEB_RELEASE_ACCEPTANCE=1` and
`python -m unittest tests.test_web_ide_release_acceptance -v`.
