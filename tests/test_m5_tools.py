import unittest
from unittest.mock import patch

from agent.tools import CandidateEvaluator, EvaluateCandidateTool, ValidateCandidateTool
from plc_tools.check import CheckResult
from plc_tools.runtime import RuntimeResult
from plc_tools.verify import VerifyResult


VALID_ST = "PROGRAM Main\nEND_PROGRAM\n"
VALID_PLAN = {
    "steps": [
        {"inputs": {"Start": False}, "expected": {"Motor": False}},
    ]
}


class M5ToolContractTests(unittest.TestCase):
    def test_invalid_candidate_is_rejected_before_checker_or_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch("agent.tools.check_st_text") as check, patch(
            "agent.tools.get_plc_status"
        ) as status:
            result = evaluator.validate("", VALID_PLAN)
        check.assert_not_called()
        status.assert_not_called()
        self.assertFalse(result["valid"])
        self.assertEqual(result["feedback"]["failure_kind"], "model_output_invalid")
        self.assertEqual(result["attempts_used"], 0)

    def test_invalid_plan_does_not_call_checker_or_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch("agent.tools.check_st_text") as check, patch(
            "agent.tools.get_plc_status"
        ) as status:
            result = evaluator.validate(VALID_ST, {"steps": []})
        check.assert_not_called()
        status.assert_not_called()
        self.assertFalse(result["valid"])
        self.assertEqual(result["attempts_used"], 0)

    def test_plan_without_assertions_or_with_invalid_timing_stays_out_of_runtime(self) -> None:
        for plan in (
            {"steps": [{"inputs": {"Start": True}, "expected": {}}]},
            {"steps": [{"inputs": {"Start": True}, "expected": {"Motor": True},
                        "settle_ms": -1}]},
        ):
            with self.subTest(plan=plan), patch("agent.tools.check_st_text") as check, patch(
                "agent.tools.get_plc_status"
            ) as status:
                result = CandidateEvaluator(
                    max_attempts=3, source_filename="candidate.st"
                ).validate(VALID_ST, plan)
            self.assertFalse(result["valid"])
            self.assertEqual(result["attempts_used"], 0)
            check.assert_not_called()
            status.assert_not_called()

    def test_syntax_failure_does_not_spend_runtime_attempt(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch(
            "agent.tools.check_st_text", return_value=CheckResult(False, [], [])
        ), patch("agent.tools.get_plc_status") as status:
            result = evaluator.validate(VALID_ST, VALID_PLAN)
        status.assert_not_called()
        self.assertFalse(result["valid"])
        self.assertEqual(result["feedback"]["failure_kind"], "candidate_check_failed")
        self.assertEqual(result["attempts_used"], 0)
        self.assertEqual(evaluator.attempts, [])

    def test_unvalidated_or_changed_candidate_never_reaches_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch("agent.tools.get_plc_status") as status:
            unvalidated = evaluator.evaluate(VALID_ST, VALID_PLAN)
        status.assert_not_called()
        self.assertEqual(unvalidated["feedback"]["failure_kind"], "candidate_not_validated")

        with patch(
            "agent.tools.check_st_text", return_value=CheckResult(True, [], [])
        ):
            evaluator.validate(VALID_ST, VALID_PLAN)
        with patch("agent.tools.get_plc_status") as status:
            changed = evaluator.evaluate(VALID_ST + "(* changed *)", VALID_PLAN)
        status.assert_not_called()
        self.assertEqual(changed["feedback"]["failure_kind"], "candidate_not_validated")
        self.assertEqual(evaluator.attempts, [])

    def test_runtime_busy_is_host_preflight_and_spends_no_attempt(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        with patch(
            "agent.tools.check_st_text", return_value=CheckResult(True, [], [])
        ):
            evaluator.validate(VALID_ST, VALID_PLAN)
        busy = RuntimeResult(True, "STOPPED", "RUNNING", "already running")
        with patch("agent.tools.get_plc_status", return_value=busy), patch(
            "agent.tools.compile_st"
        ) as compile_st:
            result = evaluator.evaluate(VALID_ST, VALID_PLAN)
        compile_st.assert_not_called()
        self.assertEqual(result["feedback"]["failure_kind"], "runtime_busy")
        self.assertEqual(result["attempts_used"], 0)
        self.assertFalse(result["submission_rejected"])
        self.assertEqual(evaluator.attempts, [])

    def test_attempt_limit_counts_only_real_runtime_evaluations(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=1, source_filename="candidate.st")
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        compile_result = type(
            "Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}}
        )()
        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])):
            evaluator.validate(VALID_ST, VALID_PLAN)
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.compile_st", return_value=compile_result
        ), patch("agent.tools.start_plc", return_value=started), patch(
            "agent.tools.verify_plan", return_value=VerifyResult(False, [], [])
        ), patch("agent.tools.stop_plc", return_value=stopped):
            first = evaluator.evaluate(VALID_ST, VALID_PLAN)
        second = evaluator.evaluate(VALID_ST, VALID_PLAN)
        self.assertTrue(first["budget_exhausted"])
        self.assertEqual(second["feedback"]["failure_kind"], "attempt_limit_reached")
        self.assertEqual(len(evaluator.attempts), 1)

    def test_tool_schemas_separate_preflight_from_runtime(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        validate_tool = ValidateCandidateTool(evaluator)
        evaluate_tool = EvaluateCandidateTool(evaluator)
        self.assertEqual(validate_tool.name, "validate_candidate")
        self.assertEqual(evaluate_tool.name, "evaluate_candidate")
        self.assertEqual(set(validate_tool.inputs), {"st_code", "verification_plan", "summary"})
        self.assertEqual(set(evaluate_tool.inputs), {"st_code", "verification_plan", "summary"})

    def test_success_runs_preflight_then_serial_runtime_pipeline(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        events: list[str] = []
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        check = CheckResult(True, [], [])
        verify = VerifyResult(True, [], [])
        compile_result = type(
            "Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}}
        )()

        def mark(name, value):
            def callback(*args, **kwargs):
                events.append(name)
                return value

            return callback

        with patch("agent.tools.check_st_text", mark("check", check)), patch(
            "agent.tools.get_plc_status", mark("status", runtime)
        ), patch("agent.tools.compile_st", mark("compile", compile_result)), patch(
            "agent.tools.start_plc", mark("start", started)
        ), patch("agent.tools.verify_plan", mark("verify", verify)), patch(
            "agent.tools.stop_plc", mark("stop", stopped)
        ):
            validation = evaluator.validate(VALID_ST, VALID_PLAN)
            result = evaluator.evaluate(VALID_ST, VALID_PLAN)

        self.assertTrue(validation["valid"])
        self.assertTrue(result["accepted"])
        self.assertEqual(events, ["check", "status", "compile", "start", "verify", "stop"])
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")

    def test_verify_failure_is_not_accepted_but_runtime_is_stopped(self) -> None:
        evaluator = CandidateEvaluator(max_attempts=3, source_filename="candidate.st")
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        compile_result = type(
            "Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}}
        )()
        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])):
            evaluator.validate(VALID_ST, VALID_PLAN)
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.compile_st", return_value=compile_result
        ), patch("agent.tools.start_plc", return_value=started), patch(
            "agent.tools.verify_plan", return_value=VerifyResult(False, [], [])
        ), patch("agent.tools.stop_plc", return_value=stopped):
            result = evaluator.evaluate(VALID_ST, VALID_PLAN)

        self.assertFalse(result["accepted"])
        self.assertEqual(result["feedback"]["failure_kind"], "behavior_verification_failed")
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
