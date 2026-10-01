"""Opt-in Phase 5 acceptance against real MatIEC/OpenPLC and Chromium."""
from __future__ import annotations
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

from fastapi.testclient import TestClient
from web_ide.app import create_app
from plc_tools.mcp_adapter import PLCMCPAdapter
from plc_tools.state import load_variable_map, load_debug_state, _state_path, parse_variable_map, save_variable_map

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / 'artifacts/phase5'


@unittest.skipUnless(os.environ.get('PLC_DEBUGGER_LIVE') == '1', 'requires real MatIEC/OpenPLC and Chromium')
class OnlineDebuggerAcceptance(unittest.TestCase):
    def test_real_runtime_watch_force_timer_trace_ladder_disconnect_and_browser(self):
        from playwright.sync_api import sync_playwright
        ARTIFACT.mkdir(parents=True, exist_ok=True)
        state_file = _state_path()
        previous_state = load_debug_state()
        if os.environ.get('PLC_DEBUGGER_REUSE') == '1' and not previous_state.get('program'):
            # Restore derived compiler metadata after an unrelated unit test
            # invalidated the state file. Native hash validation remains real.
            recorded = json.loads((ARTIFACT / 'acceptance.json').read_text(encoding='utf-8'))
            program = recorded['compile']['program']
            source = Path(program['source_file']).read_text(encoding='utf-8')
            csv = (ARTIFACT / 'compiled-variables.csv').read_text(encoding='utf-8')
            save_variable_map(parse_variable_map(csv, source), identity=program)
            previous_state = load_debug_state()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            if os.environ.get('PLC_DEBUGGER_REUSE') == '1':
                # Resume browser acceptance of the already compiled test artifact
                # after an infrastructure/UI failure; preserve the exact source
                # path and bytes checked by the native Runtime program hash.
                root = Path(previous_state['program']['source_file']).parent
                root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'tests/fixtures/p5_debugger/Debug.st', root / 'Debug.st')
            shutil.copyfile(ROOT / 'tests/fixtures/p5_debugger/debug.tests.json', root / 'debug.tests.json')
            app = create_app(root)
            gateway = app.state.gateway
            evidence = {}
            try:
                if os.environ.get('PLC_DEBUGGER_REUSE') == '1':
                    compiled = {'success': True, 'program': previous_state['program'], 'duration_ms': 0,
                                'reused_build': True}
                else:
                    compiled = gateway.plc_call('compile', 'Debug.st')
                self.assertTrue(compiled['success'], compiled)
                self.assertTrue(compiled['program']['runtime_hash'])
                evidence['compile'] = {k: compiled[k] for k in ('success', 'program', 'duration_ms')}
                self.assertTrue(gateway.plc_call('start')['success'])
                debug = gateway.debug
                ids = ['main:start', 'main:stop', 'main:fault', 'main:motor', 'main.motortimer:q', 'main.motortimer:et', 'main.motor1:running', 'main.motor2:running', 'main:level', 'main:speed']
                debug.subscribe('acceptance', ids)
                first = debug.poll()
                self.assertEqual(first['runtime'], 'running', first)
                self.assertEqual(first['consistency'], 'matched')
                debug.start_trace(ids, 100)
                self.assertTrue(gateway.plc_call('force', {'main:start': True, 'main:stop': False, 'main:fault': False})['success'])
                event = debug.poll()
                self.assertTrue(event['values']['main:motor'], event)
                self.assertEqual(event['latest']['main:start']['state'], 'forced')
                self.assertTrue(event['values']['main.motor1:running'])
                self.assertFalse(event['values']['main.motor2:running'])
                # Record the real timer transition; no simulated samples.
                deadline = time.monotonic() + 5.4
                while time.monotonic() < deadline:
                    debug.poll()
                    time.sleep(.1)
                last = debug.snapshot()
                self.assertFalse(last['values']['main:motor'])
                self.assertTrue(last['values']['main.motortimer:q'])
                self.assertEqual(last['values']['main.motortimer:et'], 5000)
                debug.trace.stop()
                trace = debug.trace.data()
                summary = debug.trace.summary()
                self.assertTrue(any(p['values']['main:motor'] for p in trace['samples']))
                self.assertFalse(trace['samples'][-1]['values']['main:motor'])
                evidence['trace_summary'] = summary
                (ARTIFACT / 'real-trace.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
                self.assertTrue(gateway.plc_call('unforce', ['main:start', 'main:stop', 'main:fault'])['success'])
                self.assertFalse(debug.poll()['forced'])
                self.assertFalse(debug.poll()['values']['main:start'])

                # Real batch read performance; host Python CPU excludes Runtime/Docker.
                benchmark = []
                for count in (10, 50, 100):
                    debug.subscribe('acceptance', [f'main:bench{i:02}' for i in range(count)])
                    latencies = []
                    cpu_start, wall_start = time.process_time(), time.monotonic()
                    for _ in range(8):
                        polled = debug.poll()
                        self.assertEqual(len(polled['values']), count)
                        latencies.append(polled['poll_latency_ms'])
                        time.sleep(.25)
                    wall = time.monotonic() - wall_start
                    benchmark.append({'variables': count, 'poll_mean_ms': sum(latencies) / len(latencies), 'poll_max_ms': max(latencies), 'host_python_cpu_percent': (time.process_time() - cpu_start) / wall * 100})
                evidence['performance'] = benchmark
                verified = gateway.plc_call('verify', 'debug.tests.json')
                self.assertTrue(verified['passed'], verified)
                evidence['verify'] = verified
                self.assertTrue(gateway.plc_call('stop')['success'])

                # Browser uses the production frontend and the same real Runtime.
                with socket.socket() as reserve:
                    reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
                base = f'http://127.0.0.1:{port}'
                logs = (ARTIFACT / 'browser-server.log').open('w', encoding='utf-8')
                browser_environment = {**os.environ, 'PLC_STATE_FILE': str(state_file)}
                process = subprocess.Popen([sys.executable, '-m', 'web_ide', '--workspace', str(root), '--port', str(port)], cwd=ROOT, env=browser_environment, stdout=logs, stderr=logs, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    for _ in range(100):
                        try:
                            with urlopen(base + '/api/workspace/status', timeout=1): break
                        except OSError: time.sleep(.1)
                    with sync_playwright() as p:
                        browser = p.chromium.launch()
                        page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                        page_errors = []
                        page.on('pageerror', lambda e: page_errors.append(str(e)))
                        page.goto(base, wait_until='networkidle')
                        page.locator('.tree-file').filter(has_text='Debug.st').click()
                        page.locator('.dock-tabs').get_by_role('button', name='RUNTIME', exact=True).click()
                        page.locator('.runtime-controls').get_by_role('button', name='Start', exact=True).click()
                        page.wait_for_function("document.querySelector('.debug-toolbar strong')?.textContent === 'RUNNING'")
                        page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                        def add(query, id):
                            page.get_by_label('Search watch symbols').fill(query)
                            page.locator('.watch-matches button').filter(has_text=id).first.click()
                        add('Start', 'main:start')
                        add('Motor', 'main:motor')
                        add('Fault', 'main:fault')
                        add('Running', 'main.motor1:running')
                        add('Running', 'main.motor2:running')
                        start_row = page.locator('[data-variable-id="main:start"]')
                        motor_row = page.locator('[data-variable-id="main:motor"]')
                        start_row.get_by_role('button', name='TRUE', exact=True).click()
                        page.wait_for_function("document.querySelector('[data-variable-id=\"main:start\"] .debug-state')?.textContent === 'FORCED'")
                        page.wait_for_function("document.querySelector('[data-variable-id=\"main:motor\"] .value-cell strong')?.textContent === 'TRUE'")
                        page.locator('.dock-tabs').get_by_role('button', name='LADDER', exact=True).click()
                        page.locator('.ladder-element.energized').first.wait_for()
                        self.assertIn('LIVE OBSERVATIONS', page.locator('.ladder-caption').inner_text())
                        page.screenshot(path=str(ARTIFACT / 'live-ladder.png'))
                        page.locator('.ladder-element').filter(has_text='Motor').first.click()
                        page.locator('.dock-tabs').get_by_role('button', name='TRACE', exact=True).click()
                        add('MotorTimer.ET', 'main.motortimer:et')
                        page.get_by_role('button', name='Start Trace', exact=True).click()
                        page.locator('.uplot').wait_for()
                        page.wait_for_timeout(500)
                        page.locator('.dock-tabs').get_by_role('button', name='FORCED', exact=True).click()
                        page.get_by_role('button', name='Unforce All', exact=True).click()
                        page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                        page.wait_for_function("document.querySelector('[data-variable-id=\"main:start\"] .debug-state')?.textContent === 'NORMAL'")
                        start_row.get_by_role('button', name='TRUE', exact=True).click()
                        page.wait_for_timeout(5500)
                        page.locator('.dock-tabs').get_by_role('button', name='TRACE', exact=True).click()
                        page.get_by_role('button', name='Stop Trace', exact=True).click()
                        page.screenshot(path=str(ARTIFACT / 'trace-timeline.png'))
                        trace_summary = page.request.get(base + '/api/debug/trace?summary=true').json()
                        self.assertEqual(trace_summary['state'], 'stopped')
                        self.assertGreater(trace_summary['sample_count'], 10)
                        evidence['browser_trace_summary'] = trace_summary

                        # Persistence and no replayed values after reload.
                        page.reload(wait_until='networkidle')
                        page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                        self.assertEqual(page.locator('[data-variable-id]').count(), 5)
                        page.wait_for_timeout(400)
                        # Force an interlock and ask real Codex to diagnose it.
                        page.locator('[data-variable-id="main:fault"]').get_by_role('button', name='TRUE', exact=True).click()
                        if os.environ.get('PLC_DEBUGGER_AGENT') == '1':
                            before = page.request.get(base + '/api/agent/events').json()['events']
                            after = max((e.get('seq', 0) for e in before), default=0)
                            page.locator('.agent-compose textarea').fill('电机为什么没有启动？请先 plc_find_symbol 和 plc_find_references，再用 plc_read 一次读取 MAIN 的 Start、Stop、Fault、Motor 稳定 ID，依据实际值说明原因。不要修改源码、编译、启动或停止 Runtime。')
                            page.locator('.agent-compose').get_by_role('button', name='Send').click()
                            deadline = time.monotonic() + 240
                            while time.monotonic() < deadline:
                                payload = page.request.get(base + f'/api/agent/events?after={after}').json()
                                events = payload['events']
                                if any(e['type'] == 'agent.idle' for e in events): break
                                page.wait_for_timeout(500)
                            else: self.fail('Codex debugger turn timed out')
                            self.assertTrue(any(e['type'] == 'tool.started' and e.get('tool') == 'plc_read' for e in events), events)
                            self.assertFalse(any(e['type'] == 'agent.error' for e in events), events)
                            answer = '\n'.join(e.get('text', '') for e in events if e['type'] == 'agent.message.delta')
                            self.assertIn('Fault', answer)
                            evidence['agent_answer'] = answer
                            (ARTIFACT / 'agent-debug-events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')

                        # Source B must disable highlighter while Build A still runs.
                        source = root / 'Debug.st'; original = source.read_text(encoding='utf-8')
                        source.write_text(original + '\n(* changed source *)\n', encoding='utf-8')
                        page.locator('.debug-warning').filter(has_text='SOURCE CHANGED').wait_for(timeout=15000)
                        page.locator('.dock-tabs').get_by_role('button', name='LADDER', exact=True).click()
                        self.assertEqual(page.locator('.ladder-element.energized').count(), 0)
                        page.screenshot(path=str(ARTIFACT / 'source-runtime-mismatch.png'))
                        # Rebuild resets identity, values and trace. Exact IDs stay subscribed.
                        page.locator('.dock-tabs').get_by_role('button', name='RUNTIME', exact=True).click()
                        page.locator('.runtime-controls').get_by_role('button', name='Build & Run', exact=True).click()
                        page.wait_for_function("document.querySelector('.debug-toolbar strong')?.textContent === 'RUNNING' && !document.querySelector('.debug-warning')", timeout=30000)
                        page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                        page.locator('[data-variable-id="main:start"]').get_by_role('button', name='TRUE', exact=True).click()
                        page.wait_for_timeout(300)
                        page.locator('.dock-tabs').get_by_role('button', name='TRACE', exact=True).click()
                        page.get_by_role('button', name='Start Trace', exact=True).click()
                        # Observe editor mutations while 100 real values arrive.
                        page.request.post(base + '/api/debug/subscribe', data={'consumer': 'performance', 'variables': [f'main:bench{i:02}' for i in range(100)]})
                        page.evaluate("window.editorMutations=0; window.longTasks=[]; new MutationObserver(e=>window.editorMutations+=e.length).observe(document.querySelector('.editor-zone'),{childList:true,subtree:true,attributes:true}); new PerformanceObserver(l=>window.longTasks.push(...l.getEntries().map(e=>e.duration))).observe({entryTypes:['longtask']})")
                        page.wait_for_timeout(2200)
                        evidence['frontend_performance'] = page.evaluate('({editor_mutations:window.editorMutations,long_tasks_ms:window.longTasks})')
                        # Stop is a real disconnect from live scans, no mocked Runtime.
                        page.request.post(base + '/api/plc/stop')
                        page.wait_for_function("document.querySelector('.debug-toolbar strong')?.textContent !== 'RUNNING'", timeout=15000)
                        interrupted = page.request.get(base + '/api/debug/trace?summary=true').json()
                        self.assertEqual(interrupted['state'], 'interrupted')
                        page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                        self.assertTrue(start_row.get_by_role('button', name='TRUE', exact=True).is_disabled())
                        page.locator('.dock-tabs').get_by_role('button', name='LADDER', exact=True).click()
                        self.assertEqual(page.locator('.ladder-element.energized').count(), 0)
                        self.assertFalse(page_errors, page_errors)
                        evidence['browser_errors'] = page_errors
                        browser.close()
                finally:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                    logs.close()
            finally:
                adapter = PLCMCPAdapter(root)
                released = adapter.unforce(['main:start', 'main:stop', 'main:fault'])
                stopped = adapter.stop()
                evidence['cleanup'] = {'released': released, 'stopped': stopped}
                (ARTIFACT / 'acceptance.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': unittest.main()
