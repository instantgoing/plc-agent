"""Opt-in release acceptance through real Chromium, Codex, MatIEC, and OpenPLC."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "phase4"


@contextmanager
def browser_workspace(files: dict[str, str]):
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        workspace = Path(directory)
        for name, content in files.items():
            (workspace / name).write_text(content, encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        log = (ARTIFACTS / "release-browser-server.log").open("a", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), "web", "--workspace", str(workspace), "--port", str(port)],
            cwd=ROOT, stdout=log, stderr=log,
        )
        try:
            for _ in range(80):
                try:
                    urlopen(f"{base}/api/workspace/status", timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                raise AssertionError("Web IDE server did not start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                try:
                    yield workspace, base, page
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            log.close()


@unittest.skipUnless(os.environ.get("PLC_WEB_RELEASE_ACCEPTANCE") == "1", "requires real Chromium, Codex, MatIEC, and test Runtime")
class WebIDEReleaseAcceptance(unittest.TestCase):
    def test_browser_ten_second_auto_stop(self):
        files = {
            "motor.st": (ROOT / "tests/fixtures/phase1_motor/motor.st").read_text(encoding="utf-8"),
            "motor.tests.json": (ROOT / "tests/fixtures/phase1_motor/motor.tests.json").read_text(encoding="utf-8"),
        }
        with browser_workspace(files) as (_, base, page):
            self.assertEqual(page.request.get(f"{base}/api/plc/status").json()["state"], "stopped")
            try:
                page.goto(base, wait_until="networkidle")
                page.locator(".tree-file").filter(has_text="motor.st").click()
                page.locator(".monaco-editor .view-lines").filter(has_text="PROGRAM").wait_for()
                page.locator(".dock-tabs").get_by_role("button", name="RUNTIME").click()
                with page.expect_response("**/api/plc/compile", timeout=120000) as compiled_response:
                    page.get_by_role("button", name="Build & Run").click()
                compiled = compiled_response.value.json()
                self.assertTrue(compiled["success"], compiled)
                page.wait_for_function("async () => (await (await fetch('/api/plc/status')).json()).state === 'running'", timeout=30000)
                page.locator(".runtime-controls select").select_option("motor.tests.json")
                with page.expect_response("**/api/plc/verify", timeout=180000) as verified_response:
                    page.get_by_role("button", name="Verify plan").click()
                verified = verified_response.value.json()
                self.assertTrue(verified["success"] and verified["passed"], verified)
                self.assertEqual(len(verified["results"]), 18)
                self.assertTrue(verified["results"][9]["actual"]["motor"])
                self.assertFalse(verified["results"][10]["actual"]["motor"])
                self.assertTrue(verified["cleanup_result"]["success"], verified)
                (ARTIFACTS / "release-ten-second.json").write_text(json.dumps(verified, indent=2), encoding="utf-8")
                page.screenshot(path=str(ARTIFACTS / "release-ten-second.png"), full_page=True)
            finally:
                page.request.post(f"{base}/api/plc/unforce", data={"variables": ["Start", "Stop"]})
                stopped = page.request.post(f"{base}/api/plc/stop", data={}).json()
                self.assertTrue(stopped["success"], stopped)

    def test_browser_compiler_error_to_codex_repair(self):
        invalid = (ROOT / "tests/fixtures/phase1_repair/broken.st").read_text(encoding="utf-8").replace(
            "Motor := Start;", "Motor := ;"
        )
        self.assertIn("Motor := ;", invalid)
        plan = {"steps": [
            {"inputs": {"Start": False}, "expected": {"Motor": False}},
            {"inputs": {"Start": True}, "expected": {"Motor": True}},
            {"inputs": {"Start": False}, "expected": {"Motor": False}},
        ]}
        with browser_workspace({"broken.st": invalid, "repair.tests.json": json.dumps(plan)}) as (workspace, base, page):
            self.assertEqual(page.request.get(f"{base}/api/plc/status").json()["state"], "stopped")
            try:
                page.goto(base, wait_until="networkidle")
                page.locator(".tree-file").filter(has_text="broken.st").click()
                page.locator(".monaco-editor .view-lines").filter(has_text="PROGRAM").wait_for()
                with page.expect_response("**/api/plc/check", timeout=30000) as checked_response:
                    page.get_by_role("button", name="Check", exact=True).click()
                checked = checked_response.value.json()
                self.assertFalse(checked["success"], checked)
                self.assertTrue(checked["diagnostics"], checked)
                page.locator(".problem-list button").first.wait_for()
                page.locator(".agent-compose textarea").fill(
                    "This is a disposable MatIEC/OpenPLC simulator workspace. First call plc_check on broken.st "
                    "and inspect its real diagnostics. Repair only the invalid Motor assignment in broken.st "
                    "so Motor follows Start. Do not change repair.tests.json. Then call plc_check, plc_compile, "
                    "plc_start, and plc_verify with repair.tests.json. Release any forced inputs and stop the "
                    "test Runtime. Report the observed verification result."
                )
                page.locator(".agent-compose").get_by_role("button", name="Send").click()
                deadline = time.monotonic() + int(os.environ.get("PLC_WEB_CODEX_TIMEOUT", "420"))
                while time.monotonic() < deadline:
                    events = page.request.get(f"{base}/api/agent/events").json()["events"]
                    if any(event["type"] == "agent.idle" for event in events):
                        break
                    page.wait_for_timeout(500)
                else:
                    page.request.post(f"{base}/api/agent/interrupt")
                    self.fail(f"Codex did not finish; recent events={events[-10:]!r}")
                (ARTIFACTS / "release-codex-repair-events.json").write_text(
                    json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                result = next(event["result"] for event in events if event["type"] == "agent.result")
                self.assertTrue(result["success"] and result["state"] == "verified", result)
                tools = [event.get("tool") for event in events if event["type"] == "tool.completed"]
                self.assertTrue({"plc_check", "plc_compile", "plc_start", "plc_verify", "plc_stop"} <= set(tools), tools)
                self.assertGreaterEqual(tools.count("plc_check"), 2, tools)
                self.assertIn("Motor := Start;", (workspace / "broken.st").read_text(encoding="utf-8"))
                self.assertEqual(json.loads((workspace / "repair.tests.json").read_text(encoding="utf-8")), plan)
                self.assertEqual(page.request.get(f"{base}/api/plc/status").json()["state"], "stopped")
                (ARTIFACTS / "release-codex-repair.json").write_text(json.dumps({
                    "initial_check_success": checked["success"],
                    "initial_diagnostics_present": bool(checked["diagnostics"]),
                    "completed_tools": tools,
                    "verify_tool_summary": next(
                        event.get("summary") for event in events
                        if event["type"] == "tool.completed" and event.get("tool") == "plc_verify"
                    ),
                    "agent_state": result["state"],
                    "changed_files": result["files_modified"],
                    "runtime_after": "stopped",
                }, indent=2), encoding="utf-8")
                page.screenshot(path=str(ARTIFACTS / "release-codex-repair.png"), full_page=True)
            finally:
                page.request.post(f"{base}/api/plc/unforce", data={"variables": ["Start"]})
                stopped = page.request.post(f"{base}/api/plc/stop", data={}).json()
                self.assertTrue(stopped["success"], stopped)


if __name__ == "__main__":
    unittest.main()
