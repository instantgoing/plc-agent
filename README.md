# plc-agent

Cross-platform PLC programming agent for IEC 61131-3 Structured Text.

The project is intentionally being built in small, verified milestones:

`natural language -> ST -> MatIEC -> C -> GCC/OpenPLC Runtime -> force/read/trace -> behavior verification`

M1 runs a real MatIEC `iec2c` compiler and returns structured diagnostics. M2
adds a real, pinned OpenPLC Runtime. M3 forces and reads real debug variables,
and M4 executes declarative behavior plans against the running scan cycle.

## M0 research and M1 compiler verification

Read [docs/research.md](docs/research.md) for the compatibility decision and
[docs/architecture.md](docs/architecture.md) for the layer boundaries.

With MatIEC installed and available as `iec2c`:

```powershell
python main.py check examples/minimal.st
python main.py check examples/invalid.st
```

The same tool boundary can use the M1 Docker image instead of a host compiler:

```powershell
docker compose -f runtime/docker-compose.m1.yml build
$env:PLC_MATIEC_DOCKER_IMAGE = "plc-agent-matiec:m1"
python main.py check examples/minimal.st
```

The compiler can be configured without changing Python code:

```powershell
$env:PLC_MATIEC_BIN = "iec2c"
$env:PLC_MATIEC_LIB = "C:/path/to/matiec/lib"
```

On Windows, an installed WSL distribution can run a Linux MatIEC release too:

```powershell
$env:PLC_MATIEC_BACKEND = "wsl"
$env:PLC_MATIEC_WSL_DISTRO = "Ubuntu"
$env:PLC_MATIEC_WSL_BIN = "/path/to/matiec/iec2c"
$env:PLC_MATIEC_WSL_LIB = "/path/to/matiec/lib"
python main.py check examples/minimal.st
```

A missing or unusable compiler is reported separately as `tool_error`; it is
never silently replaced by a parser or mock.

Run the dependency-free unit suite with:

```powershell
python -m unittest discover -s tests -v
```

Set `PLC_MATIEC_INTEGRATION=1` alongside a configured real backend to include
the valid/invalid compiler integration tests.

## M2 OpenPLC Runtime

Build the MatIEC-compatible OpenPLC base from its pinned commit, then build and
start the M2 container:

```powershell
python runtime/scripts/build_openplc_base.py
docker compose -f runtime/docker-compose.m2.yml build
docker compose -f runtime/docker-compose.m2.yml up -d
```

Compile, load, and start a real scan cycle:

```powershell
python main.py run examples/runtime_minimal.st
python main.py status
python main.py stop
```

The M2 integration test is opt-in because it requires the real container:

```powershell
$env:PLC_OPENPLC_INTEGRATION = "1"
python -m unittest tests.test_openplc_integration -v
```

Docker, MatIEC command lines, generated artifact paths, TLS/authentication, and
OpenPLC REST details remain behind `runtime/`; callers only use `plc_tools`.

## M3 variables and M4 verification

After compiling and starting a program with located variables:

```powershell
python main.py read Start Motor
python main.py force --set Start=true
python main.py read Start Motor
python main.py force --set Start=false --release Start
```

Run a declarative behavior plan after loading its matching program:

```powershell
python main.py run examples/problem_001_solution.st
python main.py verify problems/problem_001/tests.json
python main.py stop
```

Variable access uses the Runtime's authenticated Socket.IO debug protocol.
`plc_verify` applies inputs, waits for a scan, reads actual outputs, reports
expected-versus-actual failures, and releases every forced input in `finally`.

## Current status

- M0: research recorded.
- M1: complete. The public `plc_check` contract invokes real MatIEC and returns
  structured file/line/column/range diagnostics. Valid and invalid ST were
  executed against MatIEC v4.0.11 under WSL on 2026-09-09.
- M2: complete. `plc_compile` runs MatIEC v4.0.11, packages the generated C,
  uploads it to the pinned MatIEC-era OpenPLC Runtime, waits for real GCC/link
  success, and `plc_start` confirms a stable `RUNNING` scan cycle. The real
  compile/load/start/stop integration test passed on 2026-09-17.
- M3: complete. A real `Start` force crossed an advancing PLC scan cycle and
  produced a real `Motor` output read through the OpenPLC debug protocol on
  2026-09-18.
- M4: complete. The three-case `problem_001/tests.json` plan passed against the
  real Runtime on 2026-09-18, including automatic force cleanup.
- M5: complete. On 2026-09-20, a real DeepSeek tool-calling model generated a
  motor-control candidate that passed real MatIEC checking, OpenPLC Runtime
  GCC/link, scan-cycle execution, and all five behavior assertions. The
  Runtime was stopped after verification.
- M6-M7: not started.

M4 now proves behavior only for the explicit tested cases. Compilation or
runtime startup alone still never implies program correctness.

## Phase 1 Codex migration

`python main.py agent` and `python main.py chat` now enter Codex CLI, not the
smolagents loop. Codex needs its own authentication (`codex login` or
`CODEX_API_KEY`); the previous `PLC_AGENT_API_KEY` is not Codex authentication.

```powershell
python main.py agent --workspace . "检查当前 PLC 工程，并说明主要程序结构。"
python main.py chat --workspace .
```

The workspace keeps its Codex thread ID in `.plc-agent/codex-session.json`, so
the next turn resumes the same engineering context. Codex edits files in that
workspace and invokes the existing `main.py check/compile/start/force/read/verify/stop`
commands. Command and file events stream to the terminal. ST edits without a
successful real `verify` result are reported as unverified. The CLI limits
check/compile attempts to five and command executions to forty per turn by
default. The previous model-specific flags and `--output` export are no longer
part of this entrypoint.

The real Codex acceptance tasks passed on the MatIEC/OpenPLC test Runtime.
The old M5 implementation and its vendored source remain only for historical
tests; `requirements-m5.txt` no longer installs smolagents. The active CLI
does not import or initialize the old Agent. Acceptance evidence is recorded in
[docs/phase1-acceptance.md](docs/phase1-acceptance.md).

## Legacy M5 single-Agent bounded repair loop (inactive CLI path)

The following material documents the former M5 implementation. Its CLI
examples do not describe the active Codex entrypoint.

M5 adds a PLC-specific variant of the vendored `smolagents.ToolCallingAgent`.
The P1 flow first converts the natural-language request into a transient
`RequirementSpec`. Missing addresses, timing, state, safety, or observable
behavior become `open_questions`; complete requirements proceed to candidate
generation. Candidates pass through a cheap `validate_candidate` preflight
before the Runtime-consuming `evaluate_candidate` acceptance gate. A compiler
pass or an LLM explanation alone never counts as success.

The following install command is for historical M5 tests only. The vendored
smolagents source is imported by the old test adapter, not installed as an
active Agent dependency:

```powershell
python -m pip install -r requirements-m5.txt
```

Configure a real OpenAI-compatible tool-calling model without committing the
credential:

Copy `.env.example` to `.env.local`, then set the real model id, API key, and
optional OpenAI-compatible endpoint. The `agent` command loads `.env.local`
automatically. Existing process environment variables take precedence over
file values.

```dotenv
PLC_AGENT_MODEL_ID=your-model-id
PLC_AGENT_API_KEY=your-api-key
PLC_AGENT_API_BASE=https://your-provider.example/v1
```

Alternatively, configure the same values in the current PowerShell session:

```powershell
$env:PLC_AGENT_MODEL_ID = "your-model-id"
$env:PLC_AGENT_API_KEY = "your-api-key"
$env:PLC_AGENT_API_BASE = "https://your-provider.example/v1" # optional
```

Run the bounded Agent through the CLI:

```powershell
python main.py agent "当 Start 为真且 Stop 为假时启动 Motor，Stop 为真时关闭 Motor"
python main.py agent --max-attempts 3 --max-actions 8 "your PLC requirement"
```

若需求缺少 PLC 地址、按钮语义或安全/状态规则，交互式终端会显示 Agent
提供的选项和“自定义填写”入口。选定或填写答案后，CLI 会在同一命令中把补充
内容带入下一轮有界 Agent 运行。该续跑只允许发生在任何真实 PLC 候选评估之前，
因此不会延长修复预算。默认终端输出是面向人的结果摘要、执行尝试和最终 ST；脚本
和 CI 使用 `--json` 获得完整的单个 JSON 结果。非交互 stdin 也不会等待输入。

`--requirement-file` reads a UTF-8 requirement from disk. `--output` saves only
an accepted result: it writes the verified ST file and its matching
`PROGRAM.tests.json` verification plan. Existing artifacts are protected until
you add `--overwrite`:

```powershell
python main.py agent --requirement-file requirements/motor.txt --output artifacts/motor.st
```

The two budgets are independent. `max_attempts` counts only preflight-approved
candidates that enter real Runtime evaluation. Requirement analysis, malformed
tool arguments, empty ST, invalid verification plans, and MatIEC preflight
diagnostics consume Agent actions but not Runtime attempts. `max_actions`
bounds all model actions.

P3 checks the configured model against the Agent's real tool schemas before
starting a PLC task. This extra model request validates credentials, model
availability, and tool calling without executing any PLC tool. The normal
model calls use `tool_choice=auto`; reasoning is not disabled for DeepSeek.
An endpoint that returns only prose to the tool probe fails early with
`model_tool_unsupported`. Authentication, connection, context, and malformed
tool-call errors retain distinct failure kinds. The verification plan uses
`{"steps": [{"inputs": {...}, "expected": {...}, "settle_ms": 100}]}`;
`settle_ms` waits after applying inputs, whereas optional `time_ms` is an
absolute offset from the start of verification.

P3 acceptance (2026-09-22): the configured real `deepseek-flash` endpoint
passed the tool-schema probe, asked for missing I/O/timing details without
starting Runtime, and then generated a complete Start/Stop program for an
explicit requirement. The latter passed real MatIEC checking, OpenPLC
compilation/start, seven behavior assertions, forced-input release, and Runtime
stop in one evaluation attempt. The first candidate in this exercise timed
out during MatIEC preflight; it was correctly reported as unverified and used
zero Runtime attempts. A known ST sample subsequently passed the same MatIEC
backend, and the corrected prompt led to the accepted candidate.

P1 enforces this order:

```text
natural language -> RequirementSpec -> clarify or generate
                 -> validate_candidate (real ST check, no Runtime)
                 -> evaluate_candidate (compile/start/verify/stop)
```

The exact ST and verification plan accepted by preflight are cryptographically
bound together. Changing either one requires a new preflight. The Runtime
status check is host-owned, so a busy Runtime is rejected before compilation
without consuming an evaluation attempt or stopping an existing program.

P2 adds an optional in-process `PLCSession` API for callers that need multiple
turns. It keeps the last verified ST/plan, `RequirementSpec`, recent real
verification evidence, explicitly confirmed assumptions, and at most six short
turn summaries. It does not store unbounded chat history or require a database.

```python
from agent import PLCSession

session = PLCSession(on_event=lambda event: print(event.to_dict()))
first = session.submit("Build a motor controller")
second = session.resume("Start=%IX0.0, Stop=%IX0.1, Motor=%QX0.0")
# A concurrent caller may request cooperative cancellation with session.cancel().
```

Progress events include requirement analysis, user waiting, candidate/check/
compile/start/verification/repair stages, acceptance or failure, and cleanup.
Cancellation is cooperative: the current external tool call may finish first;
verification then releases forced variables and the Agent stops its Runtime.
The existing one-shot `python main.py agent` JSON API is unchanged.

P4 adds a process-local interactive terminal conversation:

```powershell
python main.py chat
python main.py chat "Build a motor program; I/O addresses to follow"
```

`chat` resumes the same `PLCSession` after a clarification or a verified
program edit. It prints live model/check/compile/run/verification/cleanup
events, then a concise result, complete ST, verification plan, and real
expected/actual evidence. Type `/json` for the last full machine result,
`/metrics` for session counters, `/help`, or `/quit`. Ctrl+C during a turn
requests cooperative cancellation and waits for Runtime cleanup; it does not
abandon an active worker. The session is in memory only and ends with the
process. Scripts and CI should continue using `python main.py agent --json`.

P5 acceptance and the exact opt-in commands are recorded in
[docs/p5-acceptance.md](docs/p5-acceptance.md). The in-process counters include
first progress latency, grouped clarification count, rejected tool calls and
schema errors, real Runtime attempts, repair success, continuation success,
and cleanup success. A rate is `null` until its denominator is nonzero.

The P0 control protocol also permits explicit non-success outcomes. The Agent
can ask one grouped clarification question, report an unverifiable requirement,
report a safe failure, or finish after the candidate budget is exhausted. Every
JSON result includes a `state`; only an `accepted` state backed by real behavior
verification has `success: true`.

The real LLM and real OpenPLC acceptance test remains opt-in and requires
`PLC_AGENT_INTEGRATION=1` together with `PLC_OPENPLC_INTEGRATION=1`. See
[docs/m5-plan.md](docs/m5-plan.md) for the full contract and acceptance rules.
