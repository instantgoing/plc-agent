"""Real stdio protocol acceptance for static project context queries."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "tests" / "fixtures" / "p3_multi"


async def _query():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "plc_tools.mcp_server", "--project-root", str(PROJECT)],
        cwd=ROOT,
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}

            async def call(name, **arguments):
                return (await client.call_tool(name, arguments)).structured_content

            return (
                names,
                await call("plc_project_context", detail="summary"),
                await call("plc_project_context", detail="io"),
                await call("plc_find_symbol", query="Motor"),
                await call("plc_find_references", symbol="FB_Motor"),
                await call("plc_find_references", symbol="%QX0.0"),
            )


class Phase3MCPTests(unittest.TestCase):
    def test_context_tools_cover_e2e_discovery_and_io_question(self):
        names, summary, io, motor, calls, address = asyncio.run(_query())
        self.assertTrue({"plc_project_context", "plc_find_symbol", "plc_find_references"} <= names)
        self.assertTrue(summary["success"])
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["pous"], 4)
        self.assertEqual(summary["files"], 5)
        self.assertEqual(io["io"]["outputs"][0]["symbol"], "Motor")
        self.assertEqual(motor["matches"][0]["address"], "%QX0.0")
        self.assertEqual(calls["declarations"][0]["file"], "src/FB_Motor.st")
        self.assertEqual(calls["references"][0]["owner"], "MAIN")
        self.assertEqual(calls["references"][0]["file"], "src/Main.st")
        self.assertEqual(address["declarations"][0]["name"], "Motor")
        self.assertTrue(any(ref["owner"] == "MAIN" for ref in address["references"]))


if __name__ == "__main__":
    unittest.main()
