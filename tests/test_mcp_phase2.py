"""Protocol checks plus opt-in real MatIEC/OpenPLC acceptance for Phase 2."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "plc_tools.mcp_server", "--project-root", str(ROOT)],
        cwd=ROOT,
    )


async def _exercise_protocol() -> tuple[set[str], dict, dict, dict]:
    async with stdio_client(_server_params()) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            discovered = {item.name for item in (await client.list_tools()).tools}
            info = (await client.call_tool("plc_project_info")).structured_content
            missing = (await client.call_tool("plc_read", {"variables": ["DOES_NOT_EXIST"]})).structured_content
            checked = (await client.call_tool("plc_check", {"file": "examples/minimal.st"})).structured_content
            return discovered, info, missing, checked


class MCPProtocolTests(unittest.TestCase):
    def test_stdio_discovery_and_structured_results(self):
        discovered, info, missing, checked = asyncio.run(_exercise_protocol())
        self.assertEqual(discovered, {
            "plc_project_info", "plc_check", "plc_compile", "plc_start",
            "plc_stop", "plc_force", "plc_read", "plc_verify",
            "plc_project_context", "plc_find_symbol", "plc_find_references",
        })
        self.assertTrue(info["success"])
        self.assertFalse(info["capabilities"]["trace"])
        self.assertFalse(missing["success"])
        self.assertIn(missing["error"]["type"], {"unknown_variable", "read_failed"})
        self.assertIn("diagnostics", checked)


@unittest.skipUnless(os.environ.get("PLC_MATIEC_INTEGRATION") == "1", "requires real MatIEC")
class MCPMatIECTests(unittest.TestCase):
    def test_check_success_and_structured_error(self):
        async def run():
            async with stdio_client(_server_params()) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    good = (await client.call_tool("plc_check", {"file": "examples/minimal.st"})).structured_content
                    bad = (await client.call_tool("plc_check", {"file": "examples/invalid.st"})).structured_content
                    return good, bad

        good, bad = asyncio.run(run())
        self.assertTrue(good["success"], good)
        self.assertFalse(bad["success"])
        self.assertTrue(bad["diagnostics"])
        self.assertIsInstance(bad["diagnostics"][0]["line"], int)


@unittest.skipUnless(os.environ.get("PLC_OPENPLC_INTEGRATION") == "1", "requires real OpenPLC")
class MCPRuntimeTests(unittest.TestCase):
    def test_lifecycle_and_behavior_failure(self):
        async def run():
            async with stdio_client(_server_params()) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()

                    async def call(name, **arguments):
                        return (await client.call_tool(name, arguments)).structured_content

                    compiled = await call("plc_compile", file="tests/fixtures/phase1_motor/motor.st")
                    if not compiled["success"]:
                        return compiled, None, None, None, None, None
                    try:
                        started = await call("plc_start")
                        read = await call("plc_read", variables=["Motor"])
                        unknown = await call("plc_read", variables=["DOES_NOT_EXIST"])
                        failed = await call("plc_verify", file="tests/fixtures/phase2_motor_failure.tests.json")
                    finally:
                        await call("plc_force", variables={}, release=["Start", "Stop"])
                        stopped = await call("plc_stop")
                    return compiled, started, read, unknown, failed, stopped

        compiled, started, read, unknown, failed, stopped = asyncio.run(run())
        self.assertTrue(compiled["success"], compiled)
        self.assertTrue(started["success"], started)
        self.assertTrue(read["success"], read)
        self.assertEqual(unknown["error"]["type"], "unknown_variable")
        self.assertTrue(failed["success"], failed)
        self.assertFalse(failed["passed"])
        self.assertTrue(failed["failures"])
        self.assertTrue(stopped["success"], stopped)


if __name__ == "__main__":
    unittest.main()
