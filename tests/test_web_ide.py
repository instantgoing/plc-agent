"""Phase 4 gateway contracts without replacing the PLC runtime implementation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_ide.app import create_app
from web_ide.events import CodexEventAdapter
from agent.codex_client import CodexInfrastructureError


ST = "PROGRAM Main\nVAR\n  Motor AT %QX0.0 : BOOL;\nEND_VAR\nMotor := FALSE;\nEND_PROGRAM\n"


class WebIDETests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "Main.st").write_text(ST, encoding="utf-8")
        self.app = create_app(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_workspace_tree_read_save_diff_and_conflict(self):
        with TestClient(self.app) as client:
            nodes = client.get("/api/workspace/tree").json()["nodes"]
            self.assertEqual(nodes[0]["name"], "src")
            path = "src/Main.st"
            before = client.get("/api/workspace/file", params={"path": path}).json()
            saved = client.put("/api/workspace/file", json={"path": path, "content": ST + "\n", "expected_version": before["version"]})
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json()["success"])
            changed = client.get("/api/changes").json()["files"]
            self.assertEqual(changed, [{"path": path, "source": "user"}])
            diff = client.get("/api/changes/diff", params={"path": path}).json()
            self.assertEqual(diff["before"], ST)
            self.assertEqual(diff["after"], ST + "\n")
            stale = client.put("/api/workspace/file", json={"path": path, "content": "mine", "expected_version": before["version"]})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual((self.root / path).read_text(encoding="utf-8"), ST + "\n")

    def test_path_traversal_and_hidden_files_are_blocked(self):
        (self.root / ".plc-agent").mkdir(exist_ok=True)
        (self.root / ".plc-agent" / "secret.json").write_text("secret", encoding="utf-8")
        with TestClient(self.app) as client:
            for path in ("../outside.st", "/Windows/system.json", ".plc-agent/secret.json", ".hidden.json", "src/../../outside.st"):
                self.assertEqual(client.get("/api/workspace/file", params={"path": path}).status_code, 400)
            self.assertEqual(client.get("/api/workspace/file", params={"path": "src/none.st"}).status_code, 404)
            self.assertEqual(client.put("/api/workspace/file", headers={"Origin": "https://attacker.example"},
                                        json={"path": "src/Main.st", "content": "changed", "expected_version": "x"}).status_code, 403)

    def test_context_and_health(self):
        with TestClient(self.app) as client:
            context = client.get("/api/project/context?detail=pous").json()
            self.assertTrue(context["success"])
            self.assertEqual(context["items"][0]["name"], "Main")
            symbol = client.get("/api/project/symbol?query=Motor").json()
            self.assertEqual(symbol["matches"][0]["file"], "src/Main.st")
            with patch.object(self.app.state.gateway, "codex_status", return_value="ready"):
                health = client.get("/api/health").json()
            self.assertEqual(health["mcp"], "ready")
            self.assertEqual(health["project"], "ready")
            self.assertEqual(health["environment"], "simulation")

    def test_codex_health_distinguishes_authentication_from_network(self):
        gateway = self.app.state.gateway
        with patch("web_ide.service._codex_binary", return_value="codex"), \
                patch("web_ide.service.CodexClient"), \
                patch("web_ide.service.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError("offline")
            self.assertEqual(gateway.codex_status(), "network_unavailable")
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://api.openai.com/v1/models", 401, "Unauthorized", {}, None)
            self.assertEqual(gateway.codex_status(), "ready")

    def test_websocket_replay_and_duplicate_sequence(self):
        with TestClient(self.app) as client:
            gateway = self.app.state.gateway
            gateway._publish({"type": "tool.started", "tool": "plc_check", "id": "one"})
            time.sleep(0.1)
            with client.websocket_connect("/ws/events?after=0") as socket:
                first = socket.receive_json()
                ready = socket.receive_json()
                self.assertEqual(first["type"], "tool.started")
                self.assertEqual(ready["type"], "connection.ready")
                sequence = first["seq"]
            with client.websocket_connect(f"/ws/events?after={sequence}") as socket:
                self.assertEqual(socket.receive_json()["type"], "connection.ready")
            time.sleep(0.05)
            self.assertEqual(len(gateway._subscribers), 0)

    def test_plc_operations_call_existing_adapter(self):
        with TestClient(self.app) as client:
            gateway = self.app.state.gateway
            with patch.object(gateway, "plc_call", return_value={"success": True, "values": {"Motor": False}}) as operation:
                result = client.post("/api/plc/read", json={"variables": ["Motor"]}).json()
                self.assertFalse(result["values"]["Motor"])
                operation.assert_called_once_with("read", ["Motor"])
            with patch.object(gateway, "plc_call", return_value={"success": True, "applied": {"Motor": True}}) as operation:
                client.post("/api/plc/force", json={"variables": {"Motor": True}, "release": []})
                operation.assert_called_once_with("force", {"Motor": True}, [])
            with patch.object(gateway, "plc_call", return_value={"success": True, "state": "running"}) as operation:
                client.post("/api/plc/start")
                operation.assert_called_once_with("start")
            gateway.environment = "real_plc"
            self.assertEqual(client.post("/api/plc/force", json={"variables": {"Motor": True}}).status_code, 403)

    def test_agent_file_change_is_visible_in_events_and_diff(self):
        with TestClient(self.app) as client:
            source = self.root / "src" / "Main.st"
            source.write_text(ST.replace("FALSE", "TRUE"), encoding="utf-8")
            self.app.state.gateway.scan_changes("agent")
            time.sleep(0.05)
            events = client.get("/api/agent/events").json()["events"]
            self.assertTrue(any(event["type"] == "file.changed" and event["source"] == "agent" for event in events))
            diff = client.get("/api/changes/diff", params={"path": "src/Main.st"}).json()
            self.assertIn("FALSE", diff["before"])
            self.assertIn("TRUE", diff["after"])

    def test_agent_event_stream_and_thread_resume(self):
        gateway = self.app.state.gateway
        class Result:
            thread_id = "test-thread"
            def to_dict(self): return {"thread_id": self.thread_id, "files_modified": []}
        class Session:
            thread_id = None
            def run(self, message, on_event):
                on_event({"type": "thread.started", "thread_id": "test-thread"})
                on_event({"type": "item.started", "item": {"type": "mcp_tool_call", "server": "plc", "id": "tool-1", "tool": "plc_find_symbol"}})
                on_event({"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "plc", "id": "tool-1", "tool": "plc_find_symbol", "status": "completed"}})
                on_event({"type": "turn.completed"})
                self.thread_id = "test-thread"
                return Result()
            def _save(self): pass
        gateway._session = Session()
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/agent/message", json={"message": "Find Motor"}).status_code, 200)
            for _ in range(30):
                events = client.get("/api/agent/events").json()["events"]
                if any(event["type"] == "agent.idle" for event in events): break
                time.sleep(0.05)
            self.assertTrue(any(event["type"] == "tool.started" for event in events))
            self.assertTrue(any(event["type"] == "tool.completed" for event in events))
            self.assertEqual(client.get("/api/agent/sessions").json()["current_thread_id"], "test-thread")
            self.assertEqual(client.post("/api/agent/sessions/new").json()["current_thread_id"], None)
            self.assertEqual(client.post("/api/agent/sessions/resume", json={"thread_id": "test-thread"}).json()["current_thread_id"], "test-thread")

    def test_concurrent_session_lookup_creates_one_session(self):
        gateway = self.app.state.gateway
        created = []
        def make_session(*, workspace):
            time.sleep(0.03)
            instance = object()
            created.append(instance)
            return instance
        with patch("web_ide.service.CodexPLCSession", side_effect=make_session):
            with ThreadPoolExecutor(max_workers=12) as workers:
                sessions = list(workers.map(lambda _: gateway.session(), range(12)))
        self.assertEqual(len(created), 1)
        self.assertTrue(all(item is sessions[0] for item in sessions))

    def test_proxy_startup_failure_is_visible_and_does_not_leave_agent_busy(self):
        with patch("web_ide.service.ensure_local_proxy", side_effect=CodexInfrastructureError("proxy offline")), TestClient(self.app) as client:
            client.post("/api/agent/message", json={"message": "Find Motor"})
            for _ in range(30):
                events = client.get("/api/agent/events").json()["events"]
                if any(event["type"] == "agent.idle" for event in events):
                    break
                time.sleep(0.05)
            self.assertTrue(any(event["type"] == "agent.error" and event["message"] == "proxy offline" for event in events))
            self.assertFalse(client.get("/api/agent/sessions").json()["active"])


class EventAdapterTests(unittest.TestCase):
    def test_same_codex_item_id_in_two_turns_has_distinct_public_ids(self):
        raw = {"type": "item.started", "item": {"id": "item_0", "type": "mcp_tool_call", "server": "plc", "tool": "plc_check"}}
        first = CodexEventAdapter("first").convert(raw)[0]
        second = CodexEventAdapter("second").convert(raw)[0]
        self.assertNotEqual(first["id"], second["id"])

    def test_only_public_events_and_no_duplicate_message(self):
        adapter = CodexEventAdapter()
        self.assertEqual(adapter.convert({"type": "item.completed", "item": {"type": "reasoning", "text": "private"}}), [])
        first = adapter.convert({"type": "item.updated", "item": {"type": "agent_message", "id": "m1", "text": "Hello"}})
        second = adapter.convert({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": "Hello world"}})
        self.assertEqual(first[0]["text"], "Hello")
        self.assertEqual(second[0]["text"], " world")
        self.assertEqual(adapter.convert({"type": "error", "message": "upstream unavailable"})[0]["type"], "agent.error")
        self.assertEqual(adapter.convert({"type": "infrastructure.stderr", "message": "model list refresh timed out"}), [])


if __name__ == "__main__":
    unittest.main()
