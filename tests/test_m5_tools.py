import unittest
from unittest.mock import patch

from agent.tools import CandidateEvaluator, EvaluateCandidateTool
from plc_tools.check import CheckResult
from plc_tools.runtime import RuntimeResult
from plc_tools.verify import VerifyResult


VALID_PLAN = {
    "steps": [
        {"inputs": {"Start": False}, "expected": {"Motor": False}},
    ]
}


class M5ToolContractTests(unittest.TestCase):
    def test_invalid_candidate_does_not_call_plc_tools(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch("agent.tools.get_plc_status") as status:
            result = evaluator.evaluate("", VALID_PLAN)
        status.assert_not_called()
        self.assertFalse(result["accepted"])
        self.assertEqual(result["feedback"]["failure_kind"], "model_output_invalid")

    def test_invalid_plan_does_not_call_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch("agent.tools.get_plc_status") as status:
            result = evaluator.evaluate("PROGRAM Main\nEND_PROGRAM\n", {"steps": []})
        status.assert_not_called()
        self.assertFalse(result["accepted"])

    def test_attempt_limit_is_hard_and_does_not_grow_history(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=1, source_filename="candidate.st")
        first = evaluator.evaluate("PROGRAM Main\nEND_PROGRAM\n", VALID_PLAN)
        second = evaluator.evaluate("PROGRAM Main\nEND_PROGRAM\n", VALID_PLAN)
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(second["feedback"]["failure_kind"], "attempt_limit_reached")
        self.assertEqual(len(evaluator.attempts), 1)

    def test_tool_schema_is_single_candidate_submission(self) -> None:
        tool = EvaluateCandidateTool(CandidateEvaluator(max_attempts=3, source_filename="candidate.st"))
        self.assertEqual(tool.name, "evaluate_candidate")
        self.assertEqual(set(tool.inputs), {"st_code", "verification_plan", "summary"})
        self.assertEqual(tool.output_type, "object")

    def test_success_runs_serial_pipeline_and_stops_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        events: list[str] = []
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        check = CheckResult(True, [], [])
        verify = VerifyResult(True, [], [])
        compile_result = type("Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}})()

        def mark(name, value):
            def callback(*args, **kwargs):
                events.append(name)
                return value

            return callback

        with patch("agent.tools.get_plc_status", mark("status", runtime)), patch(
            "agent.tools.check_st_text", mark("check", check)
        ), patch("agent.tools.compile_st", mark("compile", compile_result)), patch(
            "agent.tools.start_plc", mark("start", started)
        ), patch("agent.tools.verify_plan", mark("verify", verify)), patch(
            "agent.tools.stop_plc", mark("stop", stopped)
        ):
            result = evaluator.evaluate("PROGRAM Main\nEND_PROGRAM\n", VALID_PLAN)

        self.assertTrue(result["accepted"])
        self.assertEqual(events, ["status", "check", "compile", "start", "verify", "stop"])
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")

    def test_verify_failure_is_not_accepted_but_runtime_is_stopped(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        check = CheckResult(True, [], [])
        verify = VerifyResult(False, [], [])
        compile_result = type("Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}})()
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.check_st_text", return_value=check
        ), patch("agent.tools.compile_st", return_value=compile_result), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=verify), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            result = evaluator.evaluate("PROGRAM Main\nEND_PROGRAM\n", VALID_PLAN)

        self.assertFalse(result["accepted"])
        self.assertEqual(result["feedback"]["failure_kind"], "behavior_verification_failed")
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
