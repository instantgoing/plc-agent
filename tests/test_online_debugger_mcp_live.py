"""Real MCP smoke for new P5 contracts; reuse the loaded accepted build."""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from plc_tools.state import load_debug_state, _state_path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('PLC_DEBUGGER_MCP_LIVE') == '1', 'requires real loaded P5 program')
class DebuggerMCPLive(unittest.TestCase):
    def test_native_snapshot_unforce_trace_range_references_and_verify(self):
        root = Path(load_debug_state()['program']['source_file']).parent
        async def exercise():
            evidence = {}
            parameters = StdioServerParameters(command=sys.executable,
                args=[str(ROOT / 'plc_mcp.py'), '--project-root', str(root)], cwd=ROOT,
                env={**os.environ, 'PLC_STATE_FILE': str(_state_path())})
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    async def call(tool, **arguments):
                        payload = (await session.call_tool(tool, arguments)).structured_content
                        evidence[tool] = payload
                        return payload
                    refs = await call('plc_find_references', symbol='main:motor')
                    self.assertGreater(refs['total'], 0)
                    try:
                        self.assertTrue((await call('plc_start'))['success'])
                        forced = await call('plc_force', variables={'main:start': True, 'main:stop': False, 'main:fault': False})
                        self.assertTrue(forced['success'], forced)
                        snapshot = await call('plc_read', variables=['main:start', 'main:motor', 'main.motor1:running', 'main.motor2:running'])
                        self.assertTrue(snapshot['values']['main:motor'], snapshot)
                        self.assertTrue(snapshot['values']['main.motor1:running'])
                        self.assertFalse(snapshot['values']['main.motor2:running'])
                        self.assertEqual(snapshot['forced']['main:start'], True)
                        trace = await call('plc_trace', variables=['main:motor', 'main:speed', 'main.motortimer:et'], duration_ms=1000, sample_interval_ms=100)
                        self.assertTrue(trace['success'], trace)
                        self.assertGreater(trace['sample_count'], 0)
                        self.assertEqual(trace['summary']['main:speed']['min'], 12.5)
                        selected = await call('plc_trace', action='range', start_ms=0, end_ms=2000)
                        self.assertGreater(len(selected['samples']), 0)
                        self.assertTrue((await call('plc_unforce', variables=['main:start', 'main:stop', 'main:fault']))['success'])
                        verified = await call('plc_verify', file='debug.tests.json')
                        self.assertTrue(verified['passed'], verified)
                    finally:
                        await call('plc_unforce', variables=['main:start', 'main:stop', 'main:fault'])
                        stopped = await call('plc_stop')
                        self.assertTrue(stopped['success'], stopped)
                        self.assertTrue((await call('plc_stop'))['success'])
            (ROOT / 'artifacts/phase5/mcp-acceptance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        asyncio.run(exercise())
