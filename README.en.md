# PLC-Agent

[简体中文](README.md) | [English](README.en.md)

PLC-Agent is a local development tool for IEC 61131-3 Structured Text (ST). It provides a browser workbench, a Codex Agent, a static PLC project index, and compilation, simulation debugging, and behavior verification with MatIEC and an OpenPLC test Runtime.

The project currently targets **local simulation and testing**. It cannot connect to, deploy to, or control a physical PLC.

![PLC-Agent Web IDE with the project tree and ST editor](reference/ours/pass9/03-editor.png)

## Features

- **Web IDE:** Browse and edit ST files; inspect compiler diagnostics, project structure, Agent activity, and file changes.
- **Codex Agent:** Understand requirements, edit ST, and check and verify results through PLC MCP tools, from the Web IDE or CLI.
- **Simulation debugging:** Run programs in the OpenPLC test Runtime, read variables, Force/Unforce, record bounded traces, and inspect a read-only Live Ladder view.
- **Behavior verification:** Apply inputs and assert observed outputs with a JSON test plan. Only a real `passed: true` result means that plan passed; compilation alone does not establish correct behavior.

## Requirements

| Purpose | Requirements |
| --- | --- |
| Web IDE | Python 3, Node.js, and npm; install `requirements-phase4.txt` and frontend dependencies |
| ST checks | MatIEC `iec2c`, using the supplied Docker compiler image or a configured local/WSL compiler |
| Simulation, debugging, and verification | Docker Engine, Docker Compose, and the project's pinned OpenPLC test Runtime; support for `linux/amd64` containers |
| Agent | An installed and authenticated Codex CLI, with network access to its model service |

Installing the Tree-sitter ST grammar from `requirements-phase4.txt` on Windows may require a C build toolchain. Image builds download pinned MatIEC, OpenPLC, and other dependencies. Real acceptance has run on a Windows host with Docker Linux containers; other host environments need their own validation.

## Quick start

Run these commands from the repository root. The example uses PowerShell; the macOS/Linux virtual environment activation command is given below.

### 1. Clone and install

```powershell
git clone https://github.com/instantgoing/plc-agent.git
cd plc-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-phase4.txt
cd frontend
npm ci
npm run build
cd ..
```

On macOS/Linux, activate with `source .venv/bin/activate`. A GitHub source ZIP also contains the active Web IDE. To run historical M5 tests, use `git clone --recurse-submodules` instead so that the `smolagents` submodule is present. The active Codex/Web IDE does not depend on that submodule.

### 2. Start the Web IDE

```powershell
python main.py web --workspace .
```

Open <http://127.0.0.1:8765>. The server listens on localhost only. `--workspace` should point to the PLC project you want to edit; when it points to the repository root, the index also includes ST files under `examples/` and `tests/`. For frontend development, run `python main.py web --workspace . --dev` and open <http://127.0.0.1:5173>.

You can now browse and edit files. Complete the setup below to run checks, simulations, or Agent tasks.

### 3. Configure MatIEC and the OpenPLC test Runtime

Start Docker, then build the supplied compiler and Runtime images from the repository root:

```powershell
docker compose -f runtime/docker-compose.m1.yml build
python runtime/scripts/build_openplc_base.py
docker compose -f runtime/docker-compose.m2.yml build
docker compose -f runtime/docker-compose.m2.yml up -d
```

Create an untracked `.env.local` in the repository root containing:

```dotenv
PLC_MATIEC_BACKEND=docker
PLC_MATIEC_DOCKER_IMAGE=plc-agent-matiec:m1
```

If MatIEC is installed locally or in WSL, you can configure another backend; see the [Runtime guide](runtime/README.md). Run `python main.py check examples/minimal.st` to confirm that a real compiler is available.

### 4. Configure the Codex Agent (optional)

Install the Codex CLI and run `codex login`, or set `CODEX_API_KEY` as supported by the Codex CLI. Then use the Agent panel in the Web IDE or the CLI:

```powershell
python main.py agent --workspace . "Inspect this PLC project and explain its main program structure."
python main.py chat --workspace .
```

If your network needs a local HTTP proxy, set `PLC_CODEX_PROXY=http://127.0.0.1:PORT` in `.env.local` and restart the Web IDE. The legacy M5 `PLC_AGENT_API_KEY` is not authentication for the active Codex entrypoint.

## Basic workflow

Use the left pane to select files or PLC symbols, edit ST in the center, work with the Agent on the right, and inspect Problems, Runtime, Variables, Watch, Trace, Live Ladder, and Changes below. Save ST before Check or Build & Run. Live variables and debugging require a running simulation program.

The CLI can also run a complete simulation verification flow:

```powershell
python main.py check examples/problem_001_solution.st
python main.py run examples/problem_001_solution.st
python main.py verify problems/problem_001/tests.json
python main.py stop
```

Inspect `passed` in the `verify` output and stop the test Runtime when done. A verification plan covers only its stated inputs, outputs, and timing. The current build contract handles one ST file at a time; Live Ladder is a read-only view of a conservative language subset.

## Project layout

| Path | Responsibility |
| --- | --- |
| `agent/` | Codex sessions, requirement handling, and the bounded repair loop |
| `plc_tools/` | Stable PLC tool and MCP contracts |
| `runtime/` | MatIEC, Docker, and OpenPLC test Runtime adapters |
| `plc_context/` | Static project index derived from ST sources |
| `web_ide/` | Local FastAPI HTTP/WebSocket gateway |
| `frontend/` | React, TypeScript, Vite, and Monaco workbench |
| `examples/`, `problems/` | Sample ST and behavior plans |
| `docs/` | Architecture, phase acceptance, and release validation records |

The Agent uses PLC capabilities through `plc_tools/`; Runtime details stay in `runtime/`. The project index is derived data, while ST source files remain the source of truth.

## Validation status and limits

Phases 1–5 have recorded real Codex, MatIEC, OpenPLC, and browser acceptance. The [release validation](docs/release-validation.md) also records an independent clone installing, starting over WebSocket, and passing a five-step simulation plan. The latest workbench UI has [build, frontend test, and real Agent UI checks](reference/ours/REPORT.md); this UI commit has not had a separate fresh-clone end-to-end acceptance run.

Only the MatIEC/OpenPLC **test simulation environment** is supported. Behavior claims apply only to plans that actually passed. Physical PLC operations, general multi-file compilation, and Ladder editing are outside the current scope. See the [architecture](docs/architecture.md) and [Phase 5 results](docs/phase5-result.md) for details.

## Development checks

```powershell
python -m unittest discover -s tests -v
cd frontend
npm test
npm run build
```

Real integration scenarios in the default Python suite may be skipped. Configure the MatIEC/OpenPLC test environment and run them separately as documented. Historical M5 tests also require the Git submodule noted above.
