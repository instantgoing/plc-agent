# Runtime adapters

M1 uses the real MatIEC `iec2c` compiler through one of three adapters:

- local executable (`PLC_MATIEC_BIN`),
- Docker image (`PLC_MATIEC_DOCKER_IMAGE`), or
- Windows WSL (`PLC_MATIEC_WSL_DISTRO`, `PLC_MATIEC_WSL_BIN`, and
  `PLC_MATIEC_WSL_LIB`).

Build the M1 compiler-only image with:

```text
docker compose -f runtime/docker-compose.m1.yml build
```

The adapter choice and all command/path translation remain inside `runtime/`.
`plc_tools.check` only sees a process result and exposes stable structured
diagnostics.

The runtime is intentionally not mocked. M2 uses the real Docker/OpenPLC
adapter and exposes compile/load/start/stop/status contracts. It does not
expose fake placeholders for later milestones.

The compatibility target is the MatIEC-era OpenPLC Runtime commit recorded in
[`../docs/research.md`](../docs/research.md). Do not use the current upstream
`main` or `latest` image without first proving that it accepts MatIEC-generated
`Config0.c`/`glueVars.c` artifacts.

## M2 real Runtime

The base build script shallow-fetches the pinned OpenPLC commit and builds it
for `linux/amd64`. The second image adds MatIEC v4.0.11, xml2st v4.0.3, and the
minimal ST-to-runtime packaging script:

```text
python runtime/scripts/build_openplc_base.py
docker compose -f runtime/docker-compose.m2.yml build
docker compose -f runtime/docker-compose.m2.yml up -d
python main.py run examples/runtime_minimal.st
```

The default container is `plc-agent-openplc-m2`. Configuration stays in the
runtime adapter through `PLC_OPENPLC_CONTAINER`, `PLC_OPENPLC_URL`,
`PLC_OPENPLC_USER`, `PLC_OPENPLC_PASSWORD`, and `PLC_OPENPLC_TLS_VERIFY`.

M3 uses the authenticated `/api/debug` Socket.IO polling namespace. The
Runtime adapter owns Engine.IO framing and the binary debug commands; the PLC
Tools layer only sees variable names, typed values, runtime ticks, and
structured failures. M4 composes those stable tools into a declarative verifier.
