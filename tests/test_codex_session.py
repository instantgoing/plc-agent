"""Contract checks for thread continuation and evidence-based PLC status."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.codex_client import CodexTurn
from agent.codex_session import CodexPLCSession


class RecordingCodex:
    def __init__(self, edit=None, commands=None, after_command=None):
        self.edit = edit
        self.commands = commands or []
        self.after_command = after_command
        self.received_thread_ids = []

    def run(self, prompt, *, workspace, thread_id, max_repair_attempts, max_commands, on_event):
        self.received_thread_ids.append(thread_id)
        on_event({"type": "thread.started", "thread_id": thread_id or "codex-thread-1"})
        if self.edit:
            self.edit(workspace)
        for index, command in enumerate(self.commands):
            on_event({"type": "item.completed", "item": command})
            if self.after_command:
                self.after_command(workspace, index)
        return CodexTurn(
            thread_id=thread_id or "codex-thread-1", completed=True, exit_code=0,
            final_answer="Task attempted", commands=self.commands,
        )


class FailedCodex(RecordingCodex):
    def run(self, prompt, *, workspace, thread_id, max_repair_attempts, max_commands, on_event):
        on_event({"type": "thread.started", "thread_id": thread_id or "codex-thread-1"})
        return CodexTurn(
            thread_id=thread_id or "codex-thread-1", error="Codex usage limit reached",
            exit_code=1, commands=self.commands,
        )


class CodexSessionTests(unittest.TestCase):
    def test_mcp_evidence_can_verify_modified_program(self):
        def mcp(tool, payload, file=None):
            return {"type": "mcp_tool_call", "server": "plc", "tool": tool,
                    "arguments": {"file": file} if file else {}, "status": "completed",
                    "result": {"structured_content": payload}, "error": None}

        calls = [
            mcp("plc_check", {"success": True, "diagnostics": []}, "motor.st"),
            mcp("plc_compile", {"success": True, "variables": []}, "motor.st"),
            mcp("plc_start", {"success": True, "state": "running"}),
            mcp("plc_verify", {"success": True, "passed": True, "results": [
                {"passed": True, "expected": {"Motor": False}, "actual": {"motor": False}}
            ]}, "motor.tests.json"),
            mcp("plc_stop", {"success": True, "state": "stopped"}),
        ]

        class MCPRecordingCodex(RecordingCodex):
            def run(self, prompt, *, workspace, thread_id, max_repair_attempts, max_commands, on_event):
                (workspace / "motor.st").write_text("PROGRAM Main\nVAR Motor : BOOL; END_VAR\nEND_PROGRAM\n")
                for item in calls:
                    on_event({"type": "item.completed", "item": item})
                return CodexTurn(completed=True, exit_code=0, final_answer="verified",
                                 mcp_calls=calls, actions=calls)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "motor.st").write_text("PROGRAM Main\nEND_PROGRAM\n")
            (workspace / "motor.tests.json").write_text('{"steps": [{"expected": {"Motor": false}}]}')
            result = CodexPLCSession(workspace=workspace, client=MCPRecordingCodex()).run("Edit motor")
        self.assertTrue(result.success)
        self.assertEqual(result.state, "verified")
        self.assertEqual(len(result.mcp_calls), 5)

    def test_codex_failure_releases_inputs_and_stops_started_runtime(self):
        compiled = {
            "type": "command_execution", "command": "python main.py compile motor.st",
            "exit_code": 0,
            "aggregated_output": json.dumps({"variables": [
                {"name": "start", "location": "%IX0.0"},
                {"name": "motor", "location": "%QX0.0"},
            ]}),
        }
        started = {"type": "command_execution", "command": "python main.py start", "exit_code": 0}
        with tempfile.TemporaryDirectory() as directory:
            with patch("plc_tools.force_variables", return_value=SimpleNamespace(success=True)) as release:
                with patch("plc_tools.stop_plc", return_value=SimpleNamespace(success=True)) as stop:
                    result = CodexPLCSession(
                        workspace=directory, client=FailedCodex(commands=[compiled, started])
                    ).run("Test motor")
        self.assertEqual(result.state, "agent_infrastructure_error")
        self.assertIn("Test Runtime cleanup completed by the harness", result.final_message)
        release.assert_called_once_with(release=["start"])
        stop.assert_called_once_with()

    def test_codex_failure_does_not_stop_runtime_already_stopped_by_turn(self):
        started = {"type": "command_execution", "command": "python main.py start", "exit_code": 0}
        stopped = {"type": "command_execution", "command": "python main.py stop", "exit_code": 0}
        with tempfile.TemporaryDirectory() as directory:
            with patch("plc_tools.stop_plc") as stop:
                result = CodexPLCSession(
                    workspace=directory, client=FailedCodex(commands=[started, stopped])
                ).run("Test motor")
        self.assertEqual(result.state, "agent_infrastructure_error")
        stop.assert_not_called()

    def test_completed_turn_cannot_leave_runtime_running(self):
        started = {"type": "command_execution", "command": "python main.py start", "exit_code": 0}
        with tempfile.TemporaryDirectory() as directory:
            with patch("plc_tools.stop_plc", return_value=SimpleNamespace(success=True)) as stop:
                result = CodexPLCSession(
                    workspace=directory, client=RecordingCodex(commands=[started])
                ).run("Start test Runtime")
        self.assertFalse(result.success)
        self.assertEqual(result.state, "runtime_cleanup_required")
        stop.assert_called_once_with()

    def test_read_only_turn_persists_thread_for_second_process(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            events = []
            first_client = RecordingCodex()
            first = CodexPLCSession(workspace=workspace, client=first_client)
            result = first.run("Describe this project", on_event=events.append)
            self.assertTrue(result.success)
            self.assertEqual(result.state, "completed")
            self.assertEqual(events[0]["type"], "thread.started")
            saved = json.loads((workspace / ".plc-agent" / "codex-session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["thread_id"], "codex-thread-1")
            second_client = RecordingCodex()
            second = CodexPLCSession(workspace=workspace, client=second_client)
            second.run("Continue in the same project")
            self.assertEqual(second_client.received_thread_ids, ["codex-thread-1"])

    def test_modified_st_needs_real_check_and_verify_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "motor.st"
            source.write_text("PROGRAM Main\nEND_PROGRAM\n", encoding="utf-8")
            (workspace / "motor.tests.json").write_text('{"steps": [{"expected": {"Motor": false}}]}', encoding="utf-8")
            def edit(path):
                (path / "motor.st").write_text("PROGRAM Main\nVAR Motor : BOOL; END_VAR\nEND_PROGRAM\n", encoding="utf-8")
            check = {"type": "command_execution", "command": 'python "project/main.py" check motor.st',
                     "exit_code": 0, "aggregated_output": '{"success": true}'}
            client = RecordingCodex(edit=edit, commands=[check])
            result = CodexPLCSession(workspace=workspace, client=client).run("Edit motor")
            self.assertFalse(result.success)
            self.assertEqual(result.state, "behavior_unverified")
            self.assertEqual(result.files_modified, ["motor.st"])

            def edit_again(path):
                with (path / "motor.st").open("a", encoding="utf-8") as stream:
                    stream.write("\n")
            verify = {"type": "command_execution", "command": 'python "project/main.py" verify motor.tests.json',
                      "exit_code": 0, "aggregated_output": '{"passed": true, "steps": [{"passed": true, "expected": {"Motor": false}, "actual": {"motor": false}}]}'}
            compile_command = {"type": "command_execution", "command": 'python "project/main.py" compile motor.st',
                               "exit_code": 0, "aggregated_output": '{"success": true}'}
            start = {"type": "command_execution", "command": 'python "project/main.py" start',
                     "exit_code": 0, "aggregated_output": '{"success": true}'}
            stop = {"type": "command_execution", "command": 'python "project/main.py" stop',
                    "exit_code": 0, "aggregated_output": '{"success": true}'}
            followup = RecordingCodex(edit=edit_again, commands=[check, compile_command, start, verify, stop])
            result2 = CodexPLCSession(workspace=workspace, client=followup).run("Continue")
            self.assertTrue(result2.success)
            self.assertEqual(result2.state, "verified")

            def edit_after_verify(path, index):
                if index == 3:
                    with (path / "motor.st").open("a", encoding="utf-8") as stream:
                        stream.write("(* untested edit *)\n")
            untested = RecordingCodex(commands=[check, compile_command, start, verify, stop],
                                      after_command=edit_after_verify)
            result3 = CodexPLCSession(workspace=workspace, client=untested).run("Edit after verify")
            self.assertFalse(result3.success)
            self.assertEqual(result3.state, "check_missing_or_failed")

    def test_empty_verify_output_cannot_prove_behavior(self):
        commands = [
            {"type": "command_execution", "command": "python main.py check motor.st",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py compile motor.st",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py start",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py verify motor.tests.json",
             "exit_code": 0, "aggregated_output": '{"passed": true, "steps": []}'},
            {"type": "command_execution", "command": "python main.py stop",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "motor.st").write_text("PROGRAM Main\nEND_PROGRAM\n")
            (workspace / "motor.tests.json").write_text('{"steps": []}')
            result = CodexPLCSession(workspace=workspace, client=RecordingCodex(commands=commands)).run("Verify")
        self.assertEqual(result.state, "completed")

    def test_interrupted_start_checks_runtime_status_and_stops_it(self):
        turn = CodexTurn(error="timed out", pending_commands=[
            {"command": "python main.py start", "type": "command_execution"}
        ])
        from agent.codex_session import _cleanup_interrupted_runtime
        with patch("plc_tools.get_plc_status", return_value=SimpleNamespace(success=True, actual_status="RUNNING")) as status:
            with patch("plc_tools.stop_plc", return_value=SimpleNamespace(success=True)) as stop:
                self.assertIn("cleanup completed", _cleanup_interrupted_runtime(turn))
        status.assert_called_once_with()
        stop.assert_called_once_with()

    def test_force_still_requires_release_after_runtime_stops(self):
        turn = CodexTurn(commands=[
            {"command": "python main.py force --set Start=true", "exit_code": 0},
            {"command": "python main.py stop", "exit_code": 0},
        ])
        from agent.codex_session import _cleanup_interrupted_runtime
        with patch("plc_tools.force_variables", return_value=SimpleNamespace(success=False, tool_error="Runtime stopped")) as release:
            message = _cleanup_interrupted_runtime(turn)
        release.assert_called_once_with(release=["start"])
        self.assertIn("Runtime stopped", message)

    def test_compiler_diagnostics_are_task_failure_not_agent_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            def edit(path):
                (path / "broken.st").write_text("PROGRAM Main\nMotor := ;\nEND_PROGRAM\n")
            failed_check = {"type": "command_execution", "command": "python main.py check broken.st",
                            "exit_code": 1, "aggregated_output": '{"errors": [{"line": 2, "message": "syntax error"}]}' }
            result = CodexPLCSession(
                workspace=workspace, client=RecordingCodex(edit=edit, commands=[failed_check])
            ).run("Repair")
            self.assertFalse(result.success)
            self.assertEqual(result.state, "check_missing_or_failed")
            self.assertIn("syntax error", result.diagnostics)
            self.assertIn("main.py check", result.last_failure)

    def test_recovered_plc_tool_failure_does_not_override_real_verification(self):
        commands = [
            {"type": "command_execution", "command": "python main.py force --release Start",
             "exit_code": 1, "aggregated_output": '{"success": false, "tool_error": "Runtime not connected"}'},
            {"type": "command_execution", "command": "python main.py check motor.st",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py compile motor.st",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py start",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
            {"type": "command_execution", "command": "python main.py verify motor.tests.json",
             "exit_code": 0, "aggregated_output": '{"passed": true, "steps": [{"passed": true, "expected": {"Motor": false}, "actual": {"motor": false}}]}'},
            {"type": "command_execution", "command": "python main.py stop",
             "exit_code": 0, "aggregated_output": '{"success": true}'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "motor.st").write_text("PROGRAM Main\nEND_PROGRAM\n")
            (workspace / "motor.tests.json").write_text('{"steps": [{"expected": {"Motor": false}}]}')
            result = CodexPLCSession(
                workspace=workspace, client=RecordingCodex(commands=commands)
            ).run("Verify motor")
        self.assertTrue(result.success)
        self.assertEqual(result.state, "verified")
        self.assertIsNone(result.last_failure)

    def test_failed_check_without_file_change_is_still_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            failed_check = {"type": "command_execution", "command": "python main.py check broken.st",
                            "exit_code": 1, "aggregated_output": '{"errors": [{"message": "syntax error"}]}' }
            result = CodexPLCSession(
                workspace=directory, client=RecordingCodex(commands=[failed_check])
            ).run("Check broken.st")
            self.assertFalse(result.success)
            self.assertEqual(result.state, "plc_tool_failed")
            self.assertIn("syntax error", result.diagnostics)

    def test_changed_verification_plan_requires_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            plan = workspace / "motor.tests.json"
            plan.write_text('{"steps": []}', encoding="utf-8")

            def edit(path):
                (path / "motor.tests.json").write_text('{"steps": [{"inputs": {}}]}', encoding="utf-8")

            result = CodexPLCSession(workspace=workspace, client=RecordingCodex(edit=edit)).run("Edit plan")
            self.assertFalse(result.success)
            self.assertEqual(result.state, "behavior_unverified")
            self.assertEqual(result.files_modified, ["motor.tests.json"])


if __name__ == "__main__":
    unittest.main()
