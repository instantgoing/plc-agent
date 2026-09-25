import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import _append_clarification, _collect_clarification, _print_agent_result, _write_verified_artifacts


class AgentClarificationCliTests(unittest.TestCase):
    def test_selected_choice_is_appended_as_explicit_requirement_context(self) -> None:
        task = _append_clarification(
            "Build a motor controller.",
            "Which address controls Motor?",
            "Use Motor at %QX0.0.",
        )
        self.assertIn("Build a motor controller.", task)
        self.assertIn("Question: Which address controls Motor?", task)
        self.assertIn("Answer: Use Motor at %QX0.0.", task)

    def test_non_interactive_input_never_blocks_for_a_clarification(self) -> None:
        stdin = io.StringIO("")
        with patch("main.sys.stdin", stdin):
            self.assertIsNone(_collect_clarification("Which address?", ["Use %IX0.0."]))

    def test_human_output_is_a_summary_not_raw_result_json(self) -> None:
        result = SimpleNamespace(
            success=False,
            state="exhausted",
            failure_kind="attempt_limit_reached",
            final_message="The candidate budget ended.",
            model_final_message="The last behavior check failed.",
            attempts=[SimpleNamespace(attempt=1, phase="failed", accepted=False)],
            st_code="PROGRAM Main\nEND_PROGRAM\n",
            verification_plan={"steps": [{"inputs": {}, "expected": {}}]},
        )
        with patch("main.sys.stdout", new_callable=io.StringIO) as stdout:
            _print_agent_result(result)
        output = stdout.getvalue()
        self.assertIn("Result: not completed", output)
        self.assertIn("Model response:", output)
        self.assertIn("--- Structured Text ---", output)
        self.assertNotIn('"failure_kind"', output)

    def test_only_verified_result_can_be_exported_with_matching_plan(self) -> None:
        result = SimpleNamespace(
            success=True,
            st_code="PROGRAM Main\nEND_PROGRAM\n",
            verification_plan={"steps": [{"inputs": {"Start": False}, "expected": {"Motor": False}}]},
        )
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "motor.st"
            st_path, plan_path = _write_verified_artifacts(result, program, overwrite=False)
            self.assertEqual(st_path.read_text(encoding="utf-8"), "PROGRAM Main\nEND_PROGRAM\n")
            self.assertEqual(json.loads(plan_path.read_text(encoding="utf-8"))["steps"][0]["expected"], {"Motor": False})
            with self.assertRaises(FileExistsError):
                _write_verified_artifacts(result, program, overwrite=False)

    def test_unverified_result_is_never_exported(self) -> None:
        result = SimpleNamespace(success=False, st_code="PROGRAM Main\nEND_PROGRAM\n", verification_plan={"steps": []})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                _write_verified_artifacts(result, Path(directory) / "motor.st", overwrite=False)


if __name__ == "__main__":
    unittest.main()
