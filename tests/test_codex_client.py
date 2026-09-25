"""Codex CLI launch and policy failures stay inside the harness boundary."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.codex_client import CodexClient


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

    def test_policy_rejection_is_an_infrastructure_error(self):
        with tempfile.TemporaryDirectory() as directory:
            client = CodexClient(executable="codex")
            process = FakeProcess(stderr="command rejected: blocked by policy\n")
            with patch.object(client, "_check_auth"), patch("agent.codex_client.subprocess.Popen", return_value=process):
                result = client.run("Edit", workspace=Path(directory))
            self.assertEqual(result.error, "Codex command was blocked by policy")

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


if __name__ == "__main__":
    unittest.main()
