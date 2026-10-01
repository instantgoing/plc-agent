"""Final real disconnect/cleanup/visual acceptance of an existing P5 build."""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from agent.env import load_project_env
from plc_tools.state import load_debug_state, _state_path
from plc_tools.mcp_adapter import PLCMCPAdapter
from web_ide.service import Gateway

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / 'artifacts/phase5'


@unittest.skipUnless(os.environ.get('PLC_DEBUGGER_POLISH') == '1', 'requires the real P5 loaded build and Chromium')
class DebuggerPolish(unittest.TestCase):
    def test_real_disconnect_stop_cleanup_and_trace_layout(self):
        from playwright.sync_api import sync_playwright
        load_project_env(ROOT)
        root = Path(load_debug_state()['program']['source_file']).parent
        adapter = PLCMCPAdapter(root)
        evidence = {}
        try:
            self.assertTrue(adapter.start()['success'])
            known = list(load_debug_state().get('forced', {}))
            if known:
                self.assertTrue(adapter.unforce(known)['success'])
            gateway = Gateway(root)
            debug = gateway.debug
            debug.subscribe('test', ['main:start', 'main:motor', 'main.motortimer:et'])
            self.assertEqual(debug.poll()['runtime'], 'running')
            debug.start_trace(['main:start'], 100)
            # Actual failed connection; Runtime continues running. No fake adapter.
            with patch.dict(os.environ, {'PLC_OPENPLC_URL': 'https://127.0.0.1:1'}):
                debug._last_status = 0
                failed = debug.poll()
            self.assertEqual(failed['runtime'], 'offline')
            self.assertEqual(failed['trace']['state'], 'interrupted')
            self.assertTrue(all(v['state'] == 'unavailable' for v in failed['latest'].values()))
            evidence['transport_disconnect'] = failed
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            logs = (ARTIFACT / 'polish-server.log').open('w', encoding='utf-8')
            process = subprocess.Popen([sys.executable, '-m', 'web_ide', '--workspace', str(root), '--port', str(port)], cwd=ROOT,
                env={**os.environ, 'PLC_STATE_FILE': str(_state_path())}, stdout=logs, stderr=logs, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
                    page.wait_for_function("document.querySelector('.debug-toolbar strong')?.textContent==='RUNNING'")
                    page.locator('.dock-tabs').get_by_role('button', name='WATCH', exact=True).click()
                    def add(query, id):
                        page.get_by_label('Search watch symbols').fill(query)
                        page.locator('.watch-matches button').filter(has_text=id).first.click()
                    add('Start', 'main:start'); add('Motor', 'main:motor')
                    page.locator('[data-variable-id="main:start"]').click(button='right')
                    page.get_by_role('menuitem', name='Force TRUE', exact=True).click()
                    page.wait_for_function("document.querySelector('[data-variable-id=\"main:motor\"] .value-cell strong')?.textContent==='TRUE'")
                    page.locator('.dock-tabs').get_by_role('button', name='LADDER', exact=True).click()
                    page.wait_for_function("[...document.querySelectorAll('.ladder-timer span')].some(e=>/^ET [0-9.]+ ms$/.test(e.textContent))")
                    self.assertGreater(page.locator('.ladder-element.energized').count(), 0)
                    page.screenshot(path=str(ARTIFACT / 'live-ladder.png'))
                    page.locator('.dock-tabs').get_by_role('button', name='TRACE', exact=True).click()
                    add('MotorTimer.ET', 'main.motortimer:et')
                    page.get_by_role('button', name='Start Trace', exact=True).click()
                    page.locator('.uplot').wait_for()
                    page.wait_for_timeout(5200)
                    page.get_by_role('button', name='Stop Trace', exact=True).click()
                    page.wait_for_function("document.querySelector('.trace-panel .panel-controls strong')?.textContent.includes('STOPPED')")
                    page.screenshot(path=str(ARTIFACT / 'trace-timeline.png'))
                    plot = page.locator('.uplot').bounding_box()
                    self.assertLess(plot['y'] + plot['height'], 1073)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 1600)
                    self.assertTrue(page.locator('.editor-zone').is_visible())
                    summary = page.request.get(base + '/api/debug/trace?summary=true').json()
                    self.assertGreater(summary['summary']['main.motortimer:et']['max'], 4000)
                    evidence['trace_summary'] = summary
                    # Measure React commits, not Monaco's own internal mutation/animation.
                    page.request.post(base + '/api/debug/subscribe', data={'consumer': 'performance', 'variables': [f'main:bench{i:02}' for i in range(100)]})
                    page.evaluate("window.longTasks=[]; new PerformanceObserver(l=>window.longTasks.push(...l.getEntries().map(e=>e.duration))).observe({entryTypes:['longtask']})")
                    page.wait_for_timeout(2000)
                    evidence['browser_long_tasks_ms'] = page.evaluate('window.longTasks')
                    # This real stop must release the known force BEFORE closing debug.
                    stopped = page.request.post(base + '/api/plc/stop').json()
                    self.assertTrue(stopped['success'], stopped)
                    page.wait_for_function("document.querySelector('.debug-toolbar strong')?.textContent!=='RUNNING'")
                    self.assertFalse(page.request.get(base + '/api/debug/state').json()['forced'])
                    evidence['stop_cleanup'] = stopped
                    self.assertFalse(page_errors, page_errors)
                    browser.close()
            finally:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                logs.close()
        finally:
            known = list(load_debug_state().get('forced', {}))
            if known:
                adapter.start()
                evidence['unforce_cleanup'] = adapter.unforce(known)
            evidence['final_stop'] = adapter.stop()
            evidence['forced_remaining'] = load_debug_state().get('forced', {})
            (ARTIFACT / 'polish-acceptance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
