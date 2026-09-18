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
- M5-M7: not started. M5 requires a real supported LLM API credential; no model
  credential is present in the current environment, so no mock completion is
  claimed.

M4 now proves behavior only for the explicit tested cases. Compilation or
runtime startup alone still never implies program correctness.
