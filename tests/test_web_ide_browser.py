"""Opt-in real Chromium + MatIEC Web IDE acceptance on a disposable workspace."""

from __future__ import annotations

import os
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
ST = "PROGRAM Main\nVAR\n  Motor AT %QX0.0 : BOOL;\nEND_VAR\nMotor := FALSE;\nEND_PROGRAM\n"


@unittest.skipUnless(os.environ.get("PLC_WEB_BROWSER_INTEGRATION") == "1", "requires local Chromium and MatIEC")
class BrowserAcceptance(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("PLC_WEB_AGENT_BROWSER_INTEGRATION") == "1", "requires real Codex and test Runtime")
    def test_real_agent_edit_diff_refresh_and_dirty_conflict(self):
        from playwright.sync_api import sync_playwright

        artifact = ROOT / "artifacts" / "phase4"
        artifact.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            workspace = Path(directory)
            source = workspace / "Motor.st"
            before = (ROOT / "tests/fixtures/p3_runtime/Motor.st").read_text(encoding="utf-8")
            source.write_text(before, encoding="utf-8")
            shutil.copyfile(ROOT / "tests/fixtures/p3_runtime/motor_fault.tests.json", workspace / "motor_fault.tests.json")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            log = (artifact / "browser-agent-server.log").open("w", encoding="utf-8")
            server = subprocess.Popen(
                [sys.executable, str(ROOT / "main.py"), "web", "--workspace", str(workspace), "--port", str(port)],
                cwd=ROOT, stdout=log, stderr=log,
            )
            try:
                for _ in range(60):
                    try:
                        urlopen(f"{base}/api/workspace/status", timeout=1).close()
                        break
                    except Exception:
                        time.sleep(0.25)
                else:
                    self.fail("Web IDE server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    def wait_turn(after=0):
                        deadline = time.monotonic() + int(os.environ.get("PLC_WEB_CODEX_TIMEOUT", "360"))
                        while time.monotonic() < deadline:
                            payload = page.request.get(f"{base}/api/agent/events?after={after}").json()
                            events = payload["events"]
                            if any(event["type"] == "agent.idle" for event in events):
                                return events
                            page.wait_for_timeout(500)
                        page.request.post(f"{base}/api/agent/interrupt")
                        self.fail(f"Agent did not finish; recent events={events[-10:]!r}")
                    try:
                        page.goto(base, wait_until="networkidle")
                        page.locator(".tree-file").filter(has_text="Motor.st").click()
                        page.locator(".monaco-editor .view-lines").filter(has_text="FUNCTION_BLOCK").wait_for(timeout=15000)
                        page.locator(".agent-compose textarea").fill(
                            "给 Motor 增加 FaultPB 故障联锁：FB_Motor 新增 Fault BOOL 输入，"
                            "Fault 为 TRUE 时 Running 必须 FALSE；MAIN 将已有 FaultPB 传入。"
                            "请先查 plc_project_context、plc_find_symbol 和 plc_find_references，"
                            "只局部修改 Motor.st，不改测试计划。使用 plc_check、plc_compile、"
                            "plc_start、plc_verify 验证 motor_fault.tests.json；释放强制变量并停止 Runtime。"
                        )
                        page.locator(".agent-compose").get_by_role("button", name="Send").click()
                        page.locator(".agent-working").wait_for(timeout=15000)
                        # Refresh during a real task must reconnect to the same backend turn.
                        page.reload(wait_until="networkidle")
                        events = wait_turn()
                        result = next(event["result"] for event in events if event["type"] == "agent.result")
                        (artifact / "browser-agent-events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
                        self.assertTrue(result["success"], result)
                        self.assertEqual(result["state"], "verified", result)
                        tools = {event.get("tool") for event in events if event["type"] == "tool.completed"}
                        self.assertTrue({"plc_find_symbol", "plc_find_references", "plc_check", "plc_compile", "plc_verify"} <= tools, tools)
                        page.locator(".agent-working").wait_for(state="hidden", timeout=10000)
                        self.assertIn("plc_verify", page.locator(".agent-stream").inner_text())
                        self.assertIn("Fault := FaultPB", page.locator(".monaco-editor").inner_text().replace("\xa0", " "))
                        self.assertEqual(page.locator(".conflict-banner").count(), 0)
                        sessions = page.request.get(f"{base}/api/agent/sessions").json()
                        thread = sessions["current_thread_id"]
                        self.assertTrue(thread)
                        page.locator(".dock-tabs").get_by_role("button", name="CHANGES").click()
                        page.locator(".changes-panel button").filter(has_text="Motor.st").click()
                        page.locator(".monaco-diff-editor").wait_for(timeout=15000)
                        diff = page.request.get(f"{base}/api/changes/diff?path=Motor.st").json()
                        self.assertEqual(diff["before"], before)
                        self.assertEqual(diff["after"], source.read_text(encoding="utf-8"))
                        self.assertEqual(diff["source"], "agent")
                        page.screenshot(path=str(artifact / "browser-agent-diff.png"), full_page=True)
                        page.get_by_role("button", name="Close diff").click()
                        page.locator(".monaco-editor").click()
                        page.keyboard.press("ControlOrMeta+End")
                        page.keyboard.insert_text("\n(* USER_UNSAVED_SENTINEL *)\n")
                        after = max(event["seq"] for event in events)
                        page.locator(".agent-compose textarea").fill(
                            "在 Motor.st 的 FB_Motor 中 Running 赋值上方加一行 ST 注释："
                            "(* Fault interlock verified *)。不改变逻辑、不修改其他文件；plc_check 后结束。"
                        )
                        page.locator(".agent-compose").get_by_role("button", name="Send").click()
                        second = wait_turn(after)
                        (artifact / "browser-agent-resume-events.json").write_text(json.dumps(second, ensure_ascii=False, indent=2), encoding="utf-8")
                        source_after = source.read_text(encoding="utf-8")
                        (artifact / "browser-agent-after.st").write_text(source_after, encoding="utf-8")
                        self.assertFalse(any(event["type"] == "agent.error" for event in second), second)
                        second_result = next(event["result"] for event in second if event["type"] == "agent.result")
                        self.assertIn("Motor.st", second_result["files_modified"], second_result)
                        self.assertIn("Fault interlock verified", source_after)
                        page.locator(".conflict-banner").wait_for(timeout=10000)
                        page.locator(".monaco-editor").click()
                        page.keyboard.press("ControlOrMeta+End")
                        page.locator(".monaco-editor .view-lines").filter(has_text="USER_UNSAVED_SENTINEL").wait_for(timeout=5000)
                        self.assertIn("USER_UNSAVED_SENTINEL", page.locator(".monaco-editor").inner_text())
                        self.assertNotIn("USER_UNSAVED_SENTINEL", source.read_text(encoding="utf-8"))
                        self.assertEqual(page.request.get(f"{base}/api/agent/sessions").json()["current_thread_id"], thread)
                        page.locator(".conflict-banner").get_by_role("button", name="View Diff").click()
                        page.locator(".monaco-diff-editor").wait_for(timeout=15000)
                        page.screenshot(path=str(artifact / "browser-agent-dirty-conflict.png"), full_page=True)
                    except Exception:
                        page.screenshot(path=str(artifact / "browser-agent-failure.png"), full_page=True)
                        raise
                    finally:
                        page.request.post(f"{base}/api/agent/interrupt")
                        page.request.post(f"{base}/api/plc/force", data={"variables": {}, "release": ["StartPB", "StopPB", "FaultPB"]})
                        page.request.post(f"{base}/api/plc/stop", data={})
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                log.close()

    def test_editor_diagnostics_and_dirty_conflict(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "Main.st"
            source.write_text(ST, encoding="utf-8")
            (workspace / "FB_Motor.st").write_text(
                "FUNCTION_BLOCK FB_Motor\nVAR_INPUT\n Start : BOOL;\nEND_VAR\nEND_FUNCTION_BLOCK\n", encoding="utf-8")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = subprocess.Popen(
                [sys.executable, str(ROOT / "main.py"), "web", "--workspace", str(workspace), "--port", str(port)],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(60):
                    try:
                        urlopen(f"http://127.0.0.1:{port}/api/workspace/status", timeout=1).close()
                        break
                    except Exception:
                        time.sleep(0.25)
                else:
                    self.fail("Web IDE server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                    page.locator(".segmented").get_by_role("button", name="PLC").click()
                    page.locator(".plc-group button").filter(has_text="FB_Motor").click()
                    page.locator(".tab").filter(has_text="FB_Motor.st").wait_for(timeout=15000)
                    page.locator(".segmented").get_by_role("button", name="FILES").click()
                    page.locator(".tree-file").filter(has_text="Main.st").click()
                    page.locator(".monaco-editor").wait_for(timeout=15000)
                    page.locator(".monaco-editor .view-lines").filter(has_text="PROGRAM").wait_for(timeout=15000)
                    self.assertIn("PROGRAM Main", page.locator(".monaco-editor").inner_text().replace("\xa0", " "))
                    page.locator(".monaco-editor").click()
                    page.keyboard.press("ControlOrMeta+A")
                    page.keyboard.insert_text(ST.replace("Motor := FALSE;", "Motor := ;"))
                    page.get_by_role("button", name="Check", exact=True).click()
                    page.locator(".problem-list button").first.wait_for(timeout=30000)
                    self.assertGreater(page.locator(".squiggly-error").count(), 0)
                    self.assertIn("Main.st", page.locator(".problem-list button").first.inner_text())
                    page.locator(".problem-list button").first.click()
                    page.locator(".monaco-editor").click()
                    page.keyboard.press("End")
                    page.keyboard.insert_text(" // unsaved")
                    source.write_text(ST, encoding="utf-8")
                    page.locator(".conflict-banner").wait_for(timeout=10000)
                    self.assertIn("File changed externally", page.locator(".conflict-banner").inner_text())
                    page.locator(".conflict-banner").get_by_role("button", name="View Diff").click()
                    page.locator(".diff-heading").wait_for(timeout=10000)
                    artifact = ROOT / "artifacts" / "phase4"
                    artifact.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(artifact / "browser-editor-conflict.png"), full_page=True)
                    page.get_by_role("button", name="Close diff").click()
                    page.locator(".dock-tabs").get_by_role("button", name="CHANGES").click()
                    page.locator(".changes-panel button").filter(has_text="Main.st").click()
                    page.locator(".diff-heading").wait_for(timeout=10000)
                    page.reload(wait_until="networkidle")
                    page.locator(".tab").filter(has_text="Main.st").wait_for(timeout=15000)
                    self.assertIn("Main.st", page.locator(".statusbar").inner_text())
                    browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()

    @unittest.skipUnless(os.environ.get("PLC_OPENPLC_INTEGRATION") == "1", "requires real test Runtime")
    def test_runtime_variables_force_and_verify_in_browser(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = (ROOT / "tests" / "fixtures" / "p3_runtime" / "Motor.st").read_text(encoding="utf-8")
            source = source.replace("    Stop : BOOL;", "    Stop : BOOL;\n    Fault : BOOL;")
            source = source.replace("Running := Start AND NOT Stop;", "Running := Start AND NOT Stop AND NOT Fault;")
            source = source.replace("MotorController(Start := StartPB, Stop := StopPB);",
                                    "MotorController(Start := StartPB, Stop := StopPB, Fault := FaultPB);")
            (workspace / "Motor.st").write_text(source, encoding="utf-8")
            shutil.copyfile(ROOT / "tests" / "fixtures" / "p3_runtime" / "motor_fault.tests.json", workspace / "motor_fault.tests.json")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = subprocess.Popen([sys.executable, str(ROOT / "main.py"), "web", "--workspace", str(workspace), "--port", str(port)],
                                      cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(60):
                    try:
                        urlopen(f"http://127.0.0.1:{port}/api/workspace/status", timeout=1).close()
                        break
                    except Exception:
                        time.sleep(0.25)
                else:
                    self.fail("Web IDE server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    try:
                        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                        page.locator(".tree-file").filter(has_text="Motor.st").click()
                        page.locator(".monaco-editor .view-lines").filter(has_text="FUNCTION_BLOCK").wait_for(timeout=15000)
                        page.locator(".dock-tabs").get_by_role("button", name="RUNTIME").click()
                        with page.expect_response("**/api/plc/compile", timeout=120000) as response:
                            page.get_by_role("button", name="Compile & Load").click()
                        self.assertTrue(response.value.json()["success"])
                        with page.expect_response("**/api/plc/start", timeout=30000) as response:
                            page.get_by_role("button", name="Start", exact=True).click()
                        self.assertTrue(response.value.json()["success"])
                        page.locator(".dock-tabs").get_by_role("button", name="VARIABLES").click()
                        page.locator("tbody tr").filter(has_text="StartPB").get_by_role("button", name="TRUE").click()
                        page.locator("tbody tr").filter(has_text="%QX0.0").locator(".value-cell").get_by_text("true", exact=True).wait_for(timeout=15000)
                        artifact = ROOT / "artifacts" / "phase4"
                        artifact.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(artifact / "browser-runtime.png"), full_page=True)
                        page.locator("tbody tr").filter(has_text="StartPB").get_by_role("button", name="Release").click()
                        page.locator(".dock-tabs").get_by_role("button", name="RUNTIME").click()
                        page.locator(".runtime-controls select").select_option("motor_fault.tests.json")
                        with page.expect_response("**/api/plc/verify", timeout=30000) as response:
                            page.get_by_role("button", name="Verify plan").click()
                        self.assertTrue(response.value.json()["passed"])
                    finally:
                        page.request.post(f"http://127.0.0.1:{port}/api/plc/force", data={"variables": {}, "release": ["StartPB", "StopPB", "FaultPB"]})
                        page.request.post(f"http://127.0.0.1:{port}/api/plc/stop", data={})
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    unittest.main()
