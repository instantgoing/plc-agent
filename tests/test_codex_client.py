"""Codex CLI launch and policy failures stay inside the harness boundary."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.codex_client import CodexClient, _codex_environment


class FakeProcess:
    def __init__(self, *, stderr="", events=None):
        events = events if events is not None else [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.completed"},
        ]
        self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
        self.stderr = io.StringIO(stderr)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


class CodexClientTests(unittest.TestCase):
    def test_dedicated_codex_proxy_stays_in_child_environment(self):
        with patch.dict("os.environ", {
            "PLC_CODEX_PROXY": "http://127.0.0.1:7897",
            "PLC_AGENT_API_KEY": "old-secret",
            "HTTPS_PROXY": "http://other-proxy:8080",
            "NO_PROXY": "example.local",
        }):
            child = _codex_environment()
        self.assertNotIn("PLC_AGENT_API_KEY", child)
        self.assertNotIn("PLC_CODEX_PROXY", child)
        self.assertEqual(child["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(child["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(child["ALL_PROXY"], "http://127.0.0.1:7897")
        self.assertIn("127.0.0.1", child["NO_PROXY"])
        self.assertIn("example.local", child["NO_PROXY"])

    def test_new_and_resumed_turns_request_writable_approval_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=FakeProcess()) as launch:
                first = client.run("Inspect", workspace=Path(directory))
                first_command = launch.call_args.args[0]
            self.assertIsNone(first.error)
            self.assertIn("--approve-for-me", first_command)
            self.assertNotIn("--sandbox", first_command)

            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=FakeProcess()) as launch:
                resumed = client.run("Edit", workspace=Path(directory), thread_id="thread-1")
                resume_command = launch.call_args.args[0]
            self.assertIsNone(resumed.error)
            self.assertEqual(resume_command[resume_command.index("--approve-for-me") + 1], "resume")
            self.assertIn("--skip-git-repo-check", resume_command)

    def test_policy_rejection_is_an_infrastructure_error(self):
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            process = FakeProcess(stderr="command rejected: blocked by policy\n")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=process):
                result = client.run("Edit", workspace=Path(directory))
            self.assertEqual(result.error, "Codex command was blocked by policy")

    def test_failed_cli_exit_preserves_actionable_stderr(self):
        process = FakeProcess(stderr="Not inside a trusted directory\n", events=[])
        process.wait = lambda timeout=None: 1
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=process):
                result = client.run("Inspect", workspace=Path(directory))
            self.assertIn("Not inside a trusted directory", result.error)

    def test_every_check_and_compile_in_one_shell_command_counts_toward_limit(self):
        command = " ; ".join(["python main.py check motor.st"] * 4 +
                             ["python main.py compile motor.st"] * 2)
        process = FakeProcess(events=[
            {"type": "item.started", "item": {"id": "cmd-1", "type": "command_execution", "command": command}},
        ])
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=process):
                result = client.run("Check", workspace=Path(directory), max_repair_attempts=5)
        self.assertTrue(result.limit_reached)
        self.assertTrue(process.terminated)
        self.assertEqual(len(result.pending_commands), 1)

    def test_mcp_check_counts_toward_repair_limit(self):
        process = FakeProcess(events=[
            {"type": "item.started", "item": {"id": f"mcp-{n}", "type": "mcp_tool_call",
                                             "server": "plc", "tool": "plc_check", "arguments": {"file": "motor.st"}}}
            for n in range(6)
        ])
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=process):
                result = client.run("Check", workspace=Path(directory), max_repair_attempts=5)
        self.assertTrue(result.limit_reached)
        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
