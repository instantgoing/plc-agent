"""Opt-in real Codex and OpenPLC gateway acceptance."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_ide.app import create_app


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("PLC_WEB_LIVE_INTEGRATION") == "1", "requires authenticated Codex and test Runtime")
class LiveGatewayAcceptance(unittest.TestCase):
    def test_codex_symbol_query_stream_and_resume(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            workspace = Path(directory)
            shutil.copyfile(ROOT / "tests" / "fixtures" / "phase1_motor" / "motor.st", workspace / "motor.st")
            app = create_app(workspace)
            with TestClient(app) as client:
                sent = client.post("/api/agent/message", json={"message": "检查当前工程，告诉我 Motor 在哪里定义。请先用 plc_find_symbol 查找，只回答位置，不要修改文件。"})
                self.assertEqual(sent.status_code, 200)
                deadline = time.monotonic() + int(os.environ.get("PLC_WEB_CODEX_TIMEOUT", "180"))
                while time.monotonic() < deadline:
                    payload = client.get("/api/agent/events").json()
                    events = payload["events"]
                    if any(event["type"] == "agent.idle" for event in events):
                        break
                    time.sleep(0.5)
                else:
                    client.post("/api/agent/interrupt")
                    self.fail(f"Codex turn did not finish; events={events[-15:]!r}")
                errors = [event for event in events if event["type"] == "agent.error"]
                self.assertFalse(errors, errors)
                self.assertTrue(any(event["type"] == "tool.started" and event.get("tool") == "plc_find_symbol" for event in events), events)
                self.assertTrue(any(event["type"] == "agent.message.delta" and "motor.st" in event.get("text", "").lower() for event in events), events)
                sessions = client.get("/api/agent/sessions").json()
                self.assertTrue(sessions["current_thread_id"])
                thread = sessions["current_thread_id"]
                client.post("/api/agent/sessions/new")
                resumed = client.post("/api/agent/sessions/resume", json={"thread_id": thread}).json()
                self.assertEqual(resumed["current_thread_id"], thread)

    def test_real_simulation_compile_force_read_verify_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = (ROOT / "tests" / "fixtures" / "p3_runtime" / "Motor.st").read_text(encoding="utf-8")
            source = source.replace("    Stop : BOOL;", "    Stop : BOOL;\n    Fault : BOOL;")
            source = source.replace("Running := Start AND NOT Stop;", "Running := Start AND NOT Stop AND NOT Fault;")
            source = source.replace("MotorController(Start := StartPB, Stop := StopPB);",
                                    "MotorController(Start := StartPB, Stop := StopPB, Fault := FaultPB);")
            (workspace / "Motor.st").write_text(source, encoding="utf-8")
            shutil.copyfile(ROOT / "tests" / "fixtures" / "p3_runtime" / "motor_fault.tests.json", workspace / "motor_fault.tests.json")
            app = create_app(workspace)
            with TestClient(app) as client:
                checked = client.post("/api/plc/check", json={"file": "Motor.st"}).json()
                self.assertTrue(checked["success"], checked)
                compiled = client.post("/api/plc/compile", json={"file": "Motor.st"}).json()
                self.assertTrue(compiled["success"], compiled)
                try:
                    started = client.post("/api/plc/start").json()
                    self.assertTrue(started["success"], started)
                    status = client.get("/api/plc/status").json()
                    self.assertEqual(status["state"], "running")
                    initial = client.post("/api/plc/read", json={"variables": ["StartPB", "Motor"]}).json()
                    self.assertFalse(initial["values"]["Motor"])
                    forced = client.post("/api/plc/force", json={"variables": {"StartPB": True}, "release": []}).json()
                    self.assertTrue(forced["success"], forced)
                    time.sleep(0.2)
                    live = client.post("/api/plc/read", json={"variables": ["StartPB", "Motor"]}).json()
                    self.assertTrue(live["values"]["Motor"], live)
                    verified = client.post("/api/plc/verify", json={"file": "motor_fault.tests.json"}).json()
                    self.assertTrue(verified["success"] and verified["passed"], verified)
                finally:
                    client.post("/api/plc/force", json={"variables": {}, "release": ["StartPB", "StopPB", "FaultPB"]})
                    stopped = client.post("/api/plc/stop").json()
                    self.assertTrue(stopped["success"], stopped)


if __name__ == "__main__":
    unittest.main()
