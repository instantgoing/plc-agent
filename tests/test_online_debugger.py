"""Phase 5 contracts. Transport stubs here test errors, never claim PLC behavior."""
import asyncio
import io
import hashlib
import json
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from plc_context.ladder import ladder_ir
from plc_tools.debug import TraceBuffer, program_state, summarize_trace
from plc_tools.state import VariableEntry, load_debug_state, parse_variable_map, program_identity, save_variable_map
from plc_tools.variables import _resolve, _decode, _serialize, read_variables, force_variables, unforce_variables
from plc_tools.runtime import RuntimeResult
from web_ide.app import create_app

ROOT = Path(__file__).resolve().parents[1]
ST = 'PROGRAM MAIN\nVAR\nStart AT %IX0.0 : BOOL;\nMotor AT %QX0.0 : BOOL;\nEND_VAR\nMotor := Start;\nEND_PROGRAM\n'
CSV = '0;FB;C.R.INST;C.R.INST;MAIN;;0;\n1;IN;C.R.INST.START;x;BOOL;BOOL;0;\n2;OUT;C.R.INST.MOTOR;x;BOOL;BOOL;0;\n'


class DebugContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'PLC_STATE_FILE': str(self.root / '.plc-agent/state.json')})
        self.env.start()
        self.source = self.root / 'Main.st'
        self.source.write_text(ST, encoding='utf-8')
        self.entries = parse_variable_map(CSV, ST)
        self.identity = program_identity(self.source, ST)
        save_variable_map(self.entries, identity=self.identity)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_stable_identity_and_scope(self):
        self.assertEqual([v.id for v in self.entries], ['main:start', 'main:motor'])
        self.assertEqual(self.entries[0].location, '%IX0.0')
        self.assertEqual(self.entries[0].owner, 'MAIN')

    def test_same_name_pou_isolation_and_ambiguity(self):
        code = 'PROGRAM P1\nVAR\nRunning:BOOL;\nEND_VAR\nEND_PROGRAM\nPROGRAM P2\nVAR\nRunning:BOOL;\nEND_VAR\nEND_PROGRAM'
        csv = '0;FB;C.R.A;x;P1;;0;\n1;VAR;C.R.A.RUNNING;x;BOOL;BOOL;0;\n2;FB;C.R.B;x;P2;;0;\n3;VAR;C.R.B.RUNNING;x;BOOL;BOOL;0;\n'
        entries = parse_variable_map(csv, code)
        self.assertEqual([v.id for v in entries], ['p1:running', 'p2:running'])
        self.assertEqual(_resolve(['Running'], entries)[1], ['Running'])
        self.assertEqual(_resolve(['p1:running'], entries)[0], [entries[0]])

    def test_same_program_multiple_instances_are_distinct(self):
        csv = CSV + CSV.replace('INST', 'SECOND')
        entries = parse_variable_map(csv, ST)
        self.assertEqual(len({v.id for v in entries}), 4)

    def test_batch_read_deduplicates_and_refuses_unsupported(self):
        entries = [*self.entries, VariableEntry('text', 'STRING', '', 2, 'main:text')]
        save_variable_map(entries)
        with patch('plc_tools.variables.run_debug_command', return_value='44 7E 00 01 00 00 00 02 00 02 01 00') as command:
            result = read_variables(['main:start', 'Start', 'main:motor', 'main:text'])
        command.assert_called_once_with('44 00 02 00 00 00 01', timeout=5.)
        self.assertEqual(result.unresolved_names, ['main:text'])
        self.assertTrue(result.variables['start'].value)

    def test_force_confirmation_unforce_and_shared_tracking(self):
        save_variable_map(self.entries)
        with patch('plc_tools.variables.run_debug_command', return_value='42 7E'):
            result = force_variables({'main:start': 'true'})
            self.assertTrue(result.success)
            self.assertEqual(result.forced, {'main:start': True})
            self.assertEqual(load_debug_state()['forced'], {'main:start': True})
            released = unforce_variables(['main:start'])
            self.assertEqual(released.released, ['main:start'])
            self.assertFalse(load_debug_state()['forced'])

    def test_rejected_force_never_creates_forced_state(self):
        save_variable_map(self.entries)
        with patch('plc_tools.variables.run_debug_command', return_value='42 81'):
            result = force_variables({'main:start': True})
        self.assertFalse(result.success)
        self.assertEqual(load_debug_state()['forced'], {})

    def test_numeric_and_time_codec(self):
        self.assertEqual(_decode('TIME', struct.pack('<ii', 4, 800000000)), 4800.)
        self.assertEqual(_serialize('TIME', 4800), struct.pack('<ii', 4, 800000000))
        self.assertEqual(_decode('DINT', _serialize('DINT', -200)), -200)
        self.assertAlmostEqual(_decode('REAL', _serialize('REAL', 12.5)), 12.5)

    def test_program_hash_and_source_mismatch(self):
        self.assertEqual(program_state(self.root)['consistency'], 'matched')
        self.assertEqual(self.identity['runtime_hash'], hashlib.md5(self.source.read_bytes()).hexdigest())
        self.source.write_text(ST.replace('Motor := Start', 'Motor := FALSE'), encoding='utf-8')
        self.assertEqual(program_state(self.root)['consistency'], 'mismatch')
        self.assertEqual(program_state(self.root.parent / 'other')['consistency'], 'unknown')

    def test_trace_lifecycle_ring_buffer_bool_edges_and_numeric(self):
        trace = TraceBuffer(3)
        trace.start([{'variable_id': 'main:motor', 'type': 'BOOL'}, {'variable_id': 'main:level', 'type': 'INT'}], 100, 'build')
        origin = trace._origin
        for index in range(5):
            trace.append({'main:motor': index > 2, 'main:level': index * 10}, index * 100, monotonic=origin + index / 10)
        self.assertEqual(len(trace.samples), 3)
        self.assertEqual(trace.dropped, 2)
        summary = trace.summary()['summary']
        self.assertEqual(summary['main:motor']['transitions'], [{'t_ms': 200, 'value': False}, {'t_ms': 300, 'value': True}])
        self.assertEqual(summary['main:level']['min'], 20)
        self.assertEqual(summary['main:level']['max'], 40)
        trace.stop()
        self.assertIsNone(trace.append({'main:motor': False}, 800))
        self.assertEqual(trace.state, 'stopped')

    def test_trace_missing_sample_interrupts(self):
        trace = TraceBuffer()
        trace.start([{'variable_id': 'main:motor', 'type': 'BOOL'}], 100, 'build')
        trace.append({}, 0)
        self.assertEqual(trace.state, 'interrupted')

    def test_summary_bounds_transition_output(self):
        samples = [{'t_ms': i, 'values': {'b': bool(i % 2)}} for i in range(1000)]
        summary = summarize_trace([{'variable_id': 'b', 'type': 'BOOL'}], samples)['b']
        self.assertEqual(len(summary['transitions']), 200)
        self.assertTrue(summary['truncated'])
        self.assertEqual(summary['transition_count'], 1000)

    def test_ladder_bool_latch_timer_instances_and_mapping(self):
        source = (ROOT / 'tests/fixtures/p5_debugger/Debug.st').read_bytes()
        ir = ladder_ir(source, 'Debug.st')
        self.assertEqual(ir['status'], 'partial')
        self.assertTrue(any(r['output']['kind'] == 'timer' for r in ir['rungs']))
        ids = {r['output'].get('variable_id') for r in ir['rungs']}
        self.assertIn('main.motor1:running', ids)
        self.assertIn('main.motor2:running', ids)
        self.assertTrue(all(r['source']['file'] == 'Debug.st' and r['source']['line'] > 0 for r in ir['rungs']))
        latch = next(r for r in ir['rungs'] if r['output'].get('variable_id') == 'main:latched')
        self.assertEqual(latch['logic']['kind'], 'series')
        self.assertEqual(latch['logic']['children'][0]['kind'], 'parallel')

    def test_ladder_for_if_arithmetic_have_explicit_fallback(self):
        source = ST.replace('Motor := Start;', 'Motor := Start; IF Start THEN Motor := FALSE; END_IF; FOR i := 1 TO 2 DO Motor := TRUE; END_FOR;')
        ir = ladder_ir(source.encode(), 'Main.st')
        self.assertEqual(len(ir['rungs']), 1)
        self.assertEqual(ir['status'], 'partial')
        self.assertEqual({u['construct'] for u in ir['unsupported']}, {'if_statement', 'for_statement'})

    def test_ladder_negated_branch_has_correct_topology(self):
        source = ST.replace('Motor := Start;', 'Motor := NOT (Start AND Motor);')
        ir = ladder_ir(source.encode(), 'Main.st')
        logic = ir['rungs'][0]['logic']
        self.assertEqual(logic['kind'], 'parallel')
        self.assertTrue(all(n['kind'] == 'not' for n in logic['children']))

    def test_debug_ids_resolve_source_references_and_instance_declarations(self):
        from plc_context import ProjectIndexer
        index = ProjectIndexer(self.root)
        found = index.find_symbol('main:motor')
        self.assertEqual(found['total'], 1)
        self.assertGreater(index.find_references('main:motor')['total'], 0)
        (self.root / 'Main.st').write_bytes((ROOT / 'tests/fixtures/p5_debugger/Debug.st').read_bytes())
        found = index.find_symbol('main.motor1:running')
        self.assertEqual(found['matches'][0]['owner'], 'FB_Motor')
        self.assertGreater(index.find_references('main.motor2:running')['total'], 0)

    def test_runtime_hash_mismatch_blocks_read_and_force(self):
        with patch('plc_tools.variables.runtime_program_hash', return_value='wrong'), patch('plc_tools.variables.run_debug_command') as send:
            result = read_variables(['main:start'])
            forced = force_variables({'main:start': True})
        self.assertFalse(result.success)
        self.assertFalse(forced.success)
        send.assert_not_called()

    def test_physical_force_is_disabled_in_core(self):
        with patch.dict(os.environ, {'PLC_RUNTIME_ENVIRONMENT': 'physical'}):
            result = force_variables({'main:start': True})
        self.assertFalse(result.success)
        self.assertIn('Level 3', result.tool_error)

    def test_selected_ide_trace_summary_and_range_stay_workspace_bound(self):
        from plc_tools.mcp_adapter import PLCMCPAdapter
        adapter = PLCMCPAdapter(self.root)
        data = {'workspace': str(self.root), 'session_id': 'ui-trace', 'state': 'stopped', 'samples': []}
        with patch.dict(os.environ, {'PLC_DEBUG_GATEWAY_URL': 'http://127.0.0.1:8765'}), patch('plc_tools.mcp_adapter.urllib.request.urlopen', side_effect=lambda *a, **k: io.StringIO(json.dumps(data))) as get:
            self.assertEqual(adapter.trace(action='summary')['session_id'], 'ui-trace')
            self.assertTrue(adapter.trace(action='range', start_ms=200, end_ms=500)['success'])
            self.assertIn('start_ms=200&end_ms=500', get.call_args.args[0])
        with patch.dict(os.environ, {'PLC_DEBUG_GATEWAY_URL': 'http://remote.example'}):
            self.assertFalse(adapter.trace(action='summary')['success'])
        data['workspace'] = str(self.root / 'other')
        with patch.dict(os.environ, {'PLC_DEBUG_GATEWAY_URL': 'http://127.0.0.1:8765'}), patch('plc_tools.mcp_adapter.urllib.request.urlopen', return_value=io.StringIO(json.dumps(data))):
            self.assertFalse(adapter.trace(action='summary')['success'])

    def test_stop_releases_known_forces_before_stopping(self):
        from plc_tools.runtime import stop_plc
        from plc_tools.variables import ForceVariablesResult
        from plc_tools.state import record_forces
        from runtime.openplc import RuntimeCommandResult
        record_forces({'main:start': True}, [])
        operations = []
        def release(*args, **kwargs):
            operations.append('release')
            record_forces({}, ['main:start'])
            return ForceVariablesResult(True, {}, ['main:start'], [])
        def stop(*args, **kwargs):
            operations.append('stop')
            return RuntimeCommandResult('STOPPED', 'ok')
        with patch('plc_tools.variables._force_variables', side_effect=release), patch('plc_tools.runtime.runtime_command', side_effect=stop):
            result = stop_plc()
        self.assertTrue(result.success)
        self.assertEqual(operations, ['release', 'stop'])

    def test_runtime_command_is_idempotent_when_already_stopped(self):
        from runtime.openplc import runtime_command
        with patch('runtime.openplc._require_running_container'), patch('runtime.openplc._RuntimeClient') as client:
            client.return_value.status.return_value = 'STOPPED'
            result = runtime_command('STOPPED', timeout=1)
        self.assertEqual(result.actual_status, 'STOPPED')
        client.return_value.command.assert_not_called()

    def test_subscription_union_batch_update_offline_and_stale(self):
        app = create_app(self.root)
        debug = app.state.gateway.debug
        debug.subscribe('watch', ['main:start'])
        debug.subscribe('ladder', ['main:start', 'main:motor'])
        debug.runtime = 'running'
        debug._last_status = time.monotonic()
        with patch.object(app.state.gateway, 'plc_call', return_value={'runtime': 'running', 'values': {'main:start': True, 'main:motor': True}, 'timestamp': int(time.time() * 1000), 'forced': {'main:start': True}}) as read:
            event = debug.poll()
        read.assert_called_once_with('read', ['main:motor', 'main:start'])
        self.assertEqual(event['latest']['main:start']['state'], 'forced')
        debug.latest['main:start']['last_updated'] -= 3000
        self.assertEqual(debug.snapshot()['latest']['main:start']['state'], 'stale')
        debug._last_status = 0
        with patch('web_ide.debug_session.get_plc_status', return_value=RuntimeResult(False, None, None, '', 'disconnected')):
            event = debug.poll()
        self.assertEqual(event['runtime'], 'offline')
        self.assertEqual(event['latest']['main:motor']['state'], 'unavailable')
        debug.unsubscribe('ladder')
        self.assertEqual(debug.subscriptions, {'watch': {'main:start'}})

    def test_source_change_and_rebuild_reset_trace_without_name_remapping(self):
        app = create_app(self.root)
        debug = app.state.gateway.debug
        debug.subscribe('watch', ['main:start', 'main:removed'])
        debug.runtime = 'running'; debug._last_status = time.monotonic()
        debug._program_id = self.identity['build_id']
        debug.start_trace(['main:start'], 100)
        self.source.write_text(ST + '(* source modified *)', encoding='utf-8')
        event = debug.poll()
        self.assertEqual(event['consistency'], 'mismatch')
        self.assertEqual(event['trace']['state'], 'interrupted')
        self.assertEqual(event['latest']['main:removed']['state'], 'unresolved')
        save_variable_map(self.entries, identity=program_identity(self.source, self.source.read_text(encoding='utf-8')))
        with patch.object(app.state.gateway, 'plc_call', return_value={'runtime': 'running', 'values': {'main:start': False}}):
            event = debug.poll()
        self.assertNotEqual(event['program_id'], self.identity['build_id'])

    def test_websocket_current_debug_event_is_not_replayed(self):
        app = create_app(self.root)
        with TestClient(app) as client:
            gateway = app.state.gateway
            with client.websocket_connect('/ws/events') as socket:
                self.assertEqual(socket.receive_json()['type'], 'connection.ready')
                self.assertEqual(socket.receive_json()['type'], 'debug.values')
                gateway._publish({'type': 'debug.values', 'timestamp': 123, 'values': {}})
                self.assertEqual(socket.receive_json()['timestamp'], 123)
            self.assertEqual(gateway.events(0), [])

    def test_gateway_force_boundary_and_debug_config(self):
        app = create_app(self.root)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/debug/config', json={'interval_ms': 10}).status_code, 400)
            self.assertEqual(client.post('/api/debug/config', json={'interval_ms': 250}).status_code, 200)
            app.state.gateway.environment = 'physical'
            self.assertEqual(client.post('/api/plc/force', json={'variables': {'main:start': True}}).status_code, 403)
            self.assertEqual(client.post('/api/plc/unforce', json={'variables': ['main:start']}).status_code, 403)
