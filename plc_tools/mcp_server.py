"""Stdio MCP transport for the existing simulation-only PLC tools."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from plc_tools.mcp_adapter import PLCMCPAdapter


def create_server(project_root: str | Path) -> MCPServer:
    adapter = PLCMCPAdapter(project_root)
    server = MCPServer(
        "plc-simulator", version="0.1.0",
        instructions="Only the MatIEC/OpenPLC test Runtime is available. Release forced variables and stop the Runtime after testing. Compilation does not prove behavior.",
    )

    def report(name: str, result: dict[str, Any]) -> dict[str, Any]:
        logging.info("%s success=%s passed=%s error=%s", name, result.get("success"),
                     result.get("passed"), (result.get("error") or {}).get("type"))
        return result

    @server.tool(description="Level 0. Read project ST files and available simulator capabilities.", structured_output=True)
    def plc_project_info() -> dict[str, Any]:
        return report("plc_project_info", adapter.project_info())

    @server.tool(description="Level 0. Query cached static PLC project context by section: summary, files, pous, globals, data_types, tasks, io, references, tests.", structured_output=True)
    def plc_project_context(detail: str = "summary", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return report("plc_project_context", adapter.project_context(detail, limit, offset))

    @server.tool(description="Level 0. Find PLC declarations by name or I/O address. Match modes: exact, prefix, substring. Returns source locations.", structured_output=True)
    def plc_find_symbol(query: str, match: str = "exact", limit: int = 100) -> dict[str, Any]:
        return report("plc_find_symbol", adapter.find_symbol(query, match, limit))

    @server.tool(description="Level 0. Find declarations and source references for a PLC symbol or I/O address.", structured_output=True)
    def plc_find_references(symbol: str, limit: int = 100) -> dict[str, Any]:
        return report("plc_find_references", adapter.find_references(symbol, limit))

    @server.tool(description="Level 0. Check one project ST file with real MatIEC; returns structured diagnostics.", structured_output=True)
    def plc_check(file: str) -> dict[str, Any]:
        return report("plc_check", adapter.check(file))

    @server.tool(description="Level 1. Compile and load one project ST file into the test Runtime.", structured_output=True)
    def plc_compile(file: str) -> dict[str, Any]:
        return report("plc_compile", adapter.compile(file))

    @server.tool(description="Level 2. Start the loaded test Runtime program.", structured_output=True)
    def plc_start() -> dict[str, Any]:
        return report("plc_start", adapter.start())

    @server.tool(description="Level 2. Stop the test Runtime program.", structured_output=True)
    def plc_stop() -> dict[str, Any]:
        return report("plc_stop", adapter.stop())

    @server.tool(description="Level 2. Force located test Runtime variables; release names with release.", structured_output=True)
    def plc_force(variables: dict[str, bool | int | float | str], release: list[str] | None = None) -> dict[str, Any]:
        return report("plc_force", adapter.force(variables, release))

    @server.tool(description="Level 0. Batch read named variables from the test Runtime.", structured_output=True)
    def plc_read(variables: list[str]) -> dict[str, Any]:
        return report("plc_read", adapter.read(variables))

    @server.tool(description="Level 2. Execute a project JSON behavior plan against the real test Runtime. A valid failed assertion returns success=true, passed=false.", structured_output=True)
    def plc_verify(file: str) -> dict[str, Any]:
        return report("plc_verify", adapter.verify(file))

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="PLC simulator MCP server")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    from agent.env import load_project_env

    load_project_env(Path(__file__).resolve().parents[1])
    os.chdir(args.project_root.resolve())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Starting PLC MCP stdio server for %s", args.project_root.resolve())
    create_server(args.project_root).run(transport="stdio")


if __name__ == "__main__":
    main()
