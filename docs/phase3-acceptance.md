# Phase 3 PLC Project Context acceptance (2026-09-25)

## Architecture Before

Codex called the simulator-only PLC MCP server, which forwarded check, compile,
run, force, read, and verify operations through `plc_tools` to MatIEC/OpenPLC.
`plc_project_info` only listed ST paths. `VARIABLES.csv` supplied compiled
Runtime debug names, types, and indices; a regex supplied `AT` locations.
There was no static project symbol or reference index. Check and compile
accepted one ST file per call.

## Architecture After

```text
Codex -> plc_project_context / plc_find_symbol / plc_find_references
      -> PLCMCPAdapter -> ProjectIndexer -> ST source adapter -> snapshot
                                               (static, disposable)
Codex -> existing PLC MCP tools -> plc_tools -> MatIEC / OpenPLC test Runtime
                                             (dynamic state and verification)
```

The context index is derived from source files. It is held in server memory,
can be rebuilt, and never stores Runtime values. The existing `plc_project_info`
response remains compatible. No persistent database, vendor adapter, UI, or
physical PLC operation was added.

## Parser Used

`tree-sitter==0.25.2` and `tree-sitter-iec61131-3-st==0.1.2` are pinned in
`requirements-phase3.txt`. The ST grammar provides AST nodes, source ranges,
and error recovery. `plc_context/st_adapter.py` extracts only known nodes;
MatIEC remains the compiler and OpenPLC remains the behavior authority.
Parser references: [grammar repository](https://github.com/HeytalePazguato/tree-sitter-iec61131-3-st),
[package release](https://pypi.org/project/tree-sitter-iec61131-3-st/0.1.2/).

## Project Model

`PLCProjectSnapshot` contains source-file status, POUs, globals, data types,
tasks, I/O bindings, references, and test-plan paths. `POU`, `Variable`,
`DataType`, `Task`, `IOBinding`, and `Reference` retain file and line/column
ranges. The ST parser is isolated from these vendor-neutral model types.

## Supported IEC Constructs

- `PROGRAM`, `FUNCTION_BLOCK`, `FUNCTION` with return type and interfaces.
- `VAR`, `VAR_INPUT`, `VAR_OUTPUT`, `VAR_IN_OUT`, `VAR_TEMP`, `VAR_GLOBAL`,
  `VAR_EXTERNAL`, and `CONSTANT` qualifiers; declaration initializers.
- Located `%I`, `%Q`, and `%M` addresses in `AT` declarations.
- Named data-type declarations and task names, intervals, and priorities.
- Direct POU calls, FB instance calls, direct globals, local variable uses,
  and simple `Instance.Member` references.

## Unsupported IEC Constructs

Ladder, FBD, SFC, vendor dialect extensions, namespaces, interfaces, methods,
properties, `VAR_ACCESS`, and `VAR_CONFIG` are not indexed semantically.
Unrecognized or incomplete syntax produces per-file diagnostics and
`complete: false`; known declarations in other files remain available. This
layer does not type-check or compile ST.

## Context MCP Tools

| Tool | Purpose |
| --- | --- |
| `plc_project_context` | Summary or one paginated section (`files`, `pous`, `globals`, `data_types`, `tasks`, `io`, `references`, `tests`). |
| `plc_find_symbol` | Exact, prefix, or substring declaration lookup, including exact I/O address lookup. |
| `plc_find_references` | Declarations and bounded references for a symbol or address. |

The tools return only requested detail and source locations. `AGENTS.md` and
the active Codex session prompt instruct Codex to use context before
non-trivial edits and to inspect real source at returned locations.

## Symbol Index

Case-insensitive names are indexed with owner, scope, type, address,
initializer, and source range. Ambiguous names return multiple declarations;
qualified names such as `FB_Motor.Running` narrow variable lookups.

## Reference Graph

The first version resolves simple calls and variable uses, including calls
through local FB instances and direct FB member access. In the multi-file
fixture it resolves `MAIN -> FB_Motor`, `MAIN -> FB_Alarm`, and
`MAIN -> FC_Scale`. It is a navigation aid, not compiler-grade semantic
resolution.

## I/O Mapping

The static adapter derives symbol, owner, type, and `%I/%Q/%M` address from
the ST AST. `parse_variable_map` now uses those parsed addresses when joining
MatIEC/OpenPLC `VARIABLES.csv` to compiled debug indices. The real compile
path disables the legacy fragment fallback. Existing `plc_force`
and `plc_read` continue to use that compiled variable map. A regex remains
only as a compatibility fallback for old callers passing declaration fragments
instead of complete ST source. Runtime values are never stored in the static
snapshot.

## Cache Strategy

One `ProjectIndexer` is built when an MCP server opens its workspace. Each query stats ST files;
only files with changed `mtime_ns` or size are reread and reparsed. Deleted
files leave the index. A parser exception or syntax error is recorded on the
affected file while the other files remain queryable. The index is memory-only.

## Files Added

- `plc_context/{model,indexer,st_adapter}.py` and package entrypoint.
- `requirements-phase3.txt`.
- Small, multi-POU, broken, and Runtime test fixtures under `tests/fixtures/p3_*`.
- `tests/test_project_context.py`, `tests/test_mcp_phase3.py`, and
  `tests/test_p3_runtime_integration.py`.
- This acceptance record.

## Files Modified

- `plc_tools/mcp_adapter.py` and `plc_tools/mcp_server.py`: three context tools.
- `plc_tools/state.py` and `plc_tools/compile.py`: AST-derived static locations
  in compiled debug mapping, with no fallback on real source compilation.
- `agent/codex_session.py` and `AGENTS.md`: context-first PLC editing rules.
- `README.md`: setup and query usage.
- `tests/test_mcp_phase2.py` and `tests/test_variables.py`: compatibility and
  shared-mapping assertions.

## Unit Test Results

`.venv/Scripts/python.exe -m unittest discover -s tests -q`: 130 tests ran,
OK, 19 skipped by their integration/environment gates. Targeted context,
protocol, and variable-map tests: 16 passed. The three new context fixture
families cover detection, scopes, locations, calls, I/O, parser failure,
ambiguous names, and single-file refresh.

## End-to-End Test Results

- Real stdio MCP client discovered all three context tools and answered the
  multi-file FB call-site and `%QX0.0` mapping queries with source locations.
  The same protocol test passed under the system `python` used by the existing
  ordinary Codex `plc` MCP registration after installing the pinned parser.
- Real Codex read-only turn used `plc_find_symbol` and `plc_find_references`,
  then read only `src/FB_Motor.st` and `src/Main.st`. It identified the
  `FB_Motor` declaration at line 1, its `MAIN` call at line 12, and
  `%QX0.0 -> MAIN.Motor` declared at line 6 and used at line 15. The harness
  returned `state: completed`, with no file changes or Runtime start.
- Real Codex edit turn first queried project context, the FB declaration,
  and its caller. It added `Fault : BOOL`, connected `FaultPB` at the call
  site, and changed the FB expression so Fault stops Motor. Real
  `plc_check` and `plc_compile` succeeded. `plc_verify` returned
  `success: true, passed: true` for all five Runtime assertions. Forced
  inputs were released, `plc_stop` returned stopped, and the harness returned
  `state: verified`.
- The repeatable Phase 3 Runtime integration test passed the same five real
  assertions. Eight existing P2 MatIEC/OpenPLC integration tests passed,
  exercising check, compile, start, read, force, verify, and stop.
  After tightening the compile-time mapping fallback, the P2 variable and
  verification tests plus the Phase 3 Runtime test passed again (3 tests).

## Performance

On this Windows host, a synthetic 40-file ST project took 214 ms for a cold
snapshot, 28 ms for a cached symbol query, and 26 ms after one file changed.
The indexer's parse counter was 41 after cold indexing and one refresh,
confirming that only one file was reparsed. These are single-run measurements,
not a general benchmark.

## Known Limitations

- The context spans multiple ST files, while existing MatIEC check/compile
  and Runtime load still accept one ST file at a time. The Runtime acceptance
  fixture therefore contains all required POUs in one file.
- There is no project manifest yet. The index includes every ST file under
  `--project-root`, so a repository root containing unrelated examples and
  intentionally broken fixtures yields a mixed, incomplete snapshot. Bind the
  server to one PLC project directory for engineering queries.
- Reference resolution covers common direct forms and cannot prove every
  cross-POU dependency. Grammar acceptance can differ from MatIEC; compiler
  results still decide validity.
- The index does not infer physical devices from addresses. `%QX0.0` means a
  located output variable here, with no hardware description.

## Technical Debt

- The declaration-fragment regex fallback in the P2 debug-map contract can
  be retired once older callers stop passing incomplete ST snippets.
- `mtime_ns + size` can miss an edit that preserves both; content hashes are
  an optional future hardening step.
- The reference graph does not yet link configuration program assignments or
  complex namespace/inheritance constructs.

## Recommended Phase 4

If a later phase needs whole-project behavior testing, add an explicit
multi-file MatIEC/OpenPLC compilation path and strengthen reference resolution
against that project manifest. Phase 4 has not been started.
