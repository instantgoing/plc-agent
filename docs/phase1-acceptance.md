# Phase 1 Codex acceptance (passed 2026-09-25)

The active path is `main.py agent/chat` -> Codex CLI -> existing `main.py`
check/compile/run/force/read/verify commands -> `plc_tools` -> Runtime.
The old smolagents path is not called by the active CLI. Its vendored source
and adapter remain for historical M5 tests, but the install requirements no
longer include smolagents.

The Windows host runs Codex CLI, Python, and the PLC workspace. MatIEC is
configured through the existing Docker adapter in `.env.local`; the OpenPLC
test Runtime also uses Docker. Ubuntu WSL is installed but currently has no
`iec2c` executable, so switching to WSL would not restore compiler testing.
Windows paths are passed to the Windows Python entrypoint, which leaves any
Docker or WSL path translation to `runtime/`.

| Test | Result through 2026-09-25 |
| --- | --- |
| A: inspect project | Real authenticated Codex read the workspace and explained the ST/program structure. Passed. |
| B: add 10-second auto-stop | Real Codex edited `tests/fixtures/phase1_motor/motor.st`, received real MatIEC diagnostics, repaired a `VAR` declaration error, and passed `check` and `compile`. Its first behavior plan failed timing assertions. The corrected 18-step plan passed on the real Runtime in the resumed Codex turn; `verify` returned `passed=true` and `cleanup_result.success=true`, followed by `stop` with `actual_status=STOPPED`. The CLI returned `State: verified`. |
| C: repair compiler error | Real Codex ran `main.py check` on `tests/fixtures/phase1_repair/broken.st`, received a real MatIEC line/column diagnostic for `Motor := ;`, changed only that expression, and reran `check` successfully. The CLI correctly reported behavior unverified rather than claiming runtime success. The required compiler-repair sequence passed. |
| D: continue with Stop button | The persisted Codex thread `01a0cdfc-6906-7101-ad3b-f60dd769eeeb` resumed, read the prior 10-second version, added `%IX0.1` Stop, and later completed the same project through real compiler repair, compilation, 18-step behavior verification, forced-input release, and Runtime stop. Passed. |

The first live launch exposed an incompatible combination of `--sandbox` and
`--approve-for-me`; the first resumed launch inherited read-only execution.
Both command configurations were corrected and the latter was retested with a
real file edit. Unit tests cover the command flags, session persistence, and
failure classification.

The original M1/M2 images had been deleted. Direct Docker Hub pulls failed due
network/DNS errors. We pulled the exact pinned Python base digest through
`mirror.gcr.io`, rebuilt `plc-agent-matiec:m1`, retrieved the pinned OpenPLC
source commit as a GitHub codeload archive when Git fetch failed, built
`plc-agent-openplc:m2-base`, then rebuilt `plc-agent-openplc:m2`. The source
archive and build context are under ignored `.plc-agent/`; no `runtime/` source
was modified. Docker's M2 health check passed. The M1/M2/force/read/verify
integration suite passed all five real tests. Independently, the Codex-edited
motor program passed an 18-step real Runtime plan, including 10-second
auto-stop and immediate Stop; forced inputs were released and the Runtime was
stopped.

The previous Codex usage-limit error was an Agent infrastructure failure, not
a compiler failure. Its aborted turn left the test Runtime running; it was
manually cleaned up. The session harness now makes a best-effort release of
located inputs and stops a Runtime that its Codex turn started but did not
stop; this failure path has unit coverage. A later live Codex run completed
the full tool sequence. A preliminary forced-input release failed while the
Runtime was stopped; the Agent recognized this as transient, then passed real
check, compile, verify, and stop. The acceptance classifier was corrected so
a recovered earlier PLC tool error cannot override later verified evidence.

After removing smolagents from `requirements-m5.txt`, the unit suite passed
105 tests (16 legacy opt-in tests skipped), active CLI imports did not load
`smolagents`, and five real MatIEC/OpenPLC integration tests passed again on
2026-09-25. Historical M5 agent files, tests, and the vendored source are kept
for provenance rather than deleted from a dirty worktree. No physical PLC was
used.
