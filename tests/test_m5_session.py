import threading
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import PLCRepairAgent, PLCSession
from agent._smolagents import Model
from plc_tools.check import CheckResult
from plc_tools.runtime import RuntimeResult
from plc_tools.variables import ForceVariablesResult
from plc_tools.verify import VerifyResult, verify_plan
from tests.test_m5_agent import ActionSequenceModel, VALID_PLAN, VALID_SPEC


ST_10 = "PROGRAM Main\n(* 10 seconds *)\nEND_PROGRAM\n"
ST_5 = "PROGRAM Main\n(* 5 seconds *)\nEND_PROGRAM\n"


class RecordingAgent(PLCRepairAgent):
    def __init__(self, model: Model):
        super().__init__(model=model)
        self.prompts: list[str] = []

    def run(self, request, **kwargs):
        self.prompts.append(request.task)
        return super().run(request, **kwargs)


def success_tools():
    runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
    started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
    stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
    compiled = SimpleNamespace(success=True, tool_error=None, to_dict=lambda: {"success": True})
    return runtime, started, stopped, compiled


class PLCSessionTests(unittest.TestCase):
    def test_question_can_resume_without_repeating_full_requirement(self):
        question = "Which addresses are Start, Stop and Motor?"
        incomplete = dict(VALID_SPEC)
        incomplete.update(inputs=[], outputs=[], observable_assertions=[], open_questions=[question])
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", incomplete),
                ("ask_user", {"question": question, "choices": []}),
                ("final_answer", {"answer": question}),
                ("submit_requirement_spec", VALID_SPEC),
                ("validate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("evaluate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("final_answer", {"answer": "verified"}),
            ]
        )
        agent = RecordingAgent(model)
        events = []
        session = PLCSession(agent=agent, on_event=events.append, max_runtime_attempts=1)
        first = session.submit("Build the motor controller; addresses to follow")
        self.assertEqual(first.state, "needs_user_input")
        self.assertEqual(first.attempts, [])
        self.assertIsNone(session.current_st)

        runtime, started, stopped, compiled = success_tools()
        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])), patch(
            "agent.tools.get_plc_status", return_value=runtime
        ), patch("agent.tools.compile_st", return_value=compiled), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=VerifyResult(True, [], [])), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            second = session.resume("Start=%IX0.0, Stop=%IX0.1, Motor=%QX0.0")
        self.assertTrue(second.success, second.to_dict())
        self.assertIn("Build the motor controller", agent.prompts[1])
        self.assertIn("Start=%IX0.0", agent.prompts[1])
        self.assertEqual(session.current_st, ST_10)
        self.assertEqual(session.turn, 2)
        self.assertEqual(len(session.turn_summaries), 2)
        self.assertEqual([event.name for event in events[:3]], [
            "requirement_analyzed", "waiting_for_user", "requirement_analyzed"
        ])
        self.assertIn("cleanup_completed", [event.name for event in events])
        self.assertTrue(all(event.session_id == session.session_id for event in events))

    def test_verified_program_can_be_modified_and_reverified(self):
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                ("validate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("evaluate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("final_answer", {"answer": "10 seconds verified"}),
                ("submit_requirement_spec", {**VALID_SPEC, "timing_rules": ["5 seconds"]}),
                ("validate_candidate", {"st_code": ST_5, "verification_plan": VALID_PLAN}),
                ("evaluate_candidate", {"st_code": ST_5, "verification_plan": VALID_PLAN}),
                ("final_answer", {"answer": "5 seconds verified"}),
            ]
        )
        agent = RecordingAgent(model)
        session = PLCSession(agent=agent, max_runtime_attempts=1)
        runtime, started, stopped, compiled = success_tools()
        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])), patch(
            "agent.tools.get_plc_status", return_value=runtime
        ), patch("agent.tools.compile_st", return_value=compiled), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=VerifyResult(True, [], [])), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            first = session.submit("Use a 10 second delay")
            second = session.resume("把刚才的 10 秒改成 5 秒")
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertIn(json.dumps(ST_10, ensure_ascii=False), agent.prompts[1])
        self.assertIn("把刚才的 10 秒改成 5 秒", agent.prompts[1])
        self.assertEqual(session.current_st, ST_5)
        self.assertEqual(session.requirement_spec.timing_rules, ["5 seconds"])
        self.assertEqual(len(session.turn_summaries), 2)
        self.assertFalse(session.cancel())

    def test_cancel_after_runtime_start_stops_runtime(self):
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                ("validate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("evaluate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("final_answer", {"answer": "cancelled"}),
            ]
        )
        session = PLCSession(agent=PLCRepairAgent(model=model), max_runtime_attempts=1)
        runtime, started, stopped, compiled = success_tools()
        events = []

        def on_event(event):
            events.append(event.name)
            if event.name == "runtime_started":
                self.assertTrue(session.cancel())

        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])), patch(
            "agent.tools.get_plc_status", return_value=runtime
        ), patch("agent.tools.compile_st", return_value=compiled), patch(
            "agent.tools.start_plc", return_value=started
        ), patch(
            "agent.tools.verify_plan",
            return_value=VerifyResult(False, [], [], "verification cancelled", True, {"success": True}),
        ), patch("agent.tools.stop_plc", return_value=stopped) as stop:
            result = session.submit("Control a motor", on_event=on_event)
        self.assertFalse(result.success)
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(result.failure_kind, "cancelled")
        stop.assert_called_once()
        self.assertIn("cleanup_completed", events)
        self.assertFalse(session.active)

    def test_event_callback_error_cannot_interrupt_runtime_cleanup(self):
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                ("validate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("evaluate_candidate", {"st_code": ST_10, "verification_plan": VALID_PLAN}),
                ("final_answer", {"answer": "verified"}),
            ]
        )
        session = PLCSession(agent=PLCRepairAgent(model=model), max_runtime_attempts=1)
        runtime, started, stopped, compiled = success_tools()
        with patch("agent.tools.check_st_text", return_value=CheckResult(True, [], [])), patch(
            "agent.tools.get_plc_status", return_value=runtime
        ), patch("agent.tools.compile_st", return_value=compiled), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=VerifyResult(True, [], [])), patch(
            "agent.tools.stop_plc", return_value=stopped
        ) as stop:
            result = session.submit(
                "Control a motor",
                on_event=lambda event: (_ for _ in ()).throw(RuntimeError("UI is gone")),
            )
        self.assertTrue(result.success)
        stop.assert_called_once()


class VerificationCancellationTests(unittest.TestCase):
    def test_cancel_releases_forced_inputs_before_return(self):
        cancel = threading.Event()
        calls = []

        def force(values=None, *, release=None):
            calls.append((values, release))
            return ForceVariablesResult(True, values or {}, release or [], [])

        read = SimpleNamespace(
            success=True,
            variables={"motor": SimpleNamespace(value=False)},
            tool_error=None,
        )
        with patch("plc_tools.verify.get_plc_status", return_value=RuntimeResult(
            True, "RUNNING", "RUNNING", "ok"
        )), patch("plc_tools.verify.force_variables", side_effect=force), patch(
            "plc_tools.verify.read_variables", return_value=read
        ):
            result = verify_plan(
                {"steps": [
                    {"inputs": {"Start": False}, "expected": {"Motor": False}, "settle_ms": 0},
                    {"inputs": {"Start": True}, "expected": {"Motor": True}, "time_ms": 5000},
                ]},
                cancel_requested=cancel.is_set,
                on_step=lambda step: cancel.set(),
            )
        self.assertTrue(result.cancelled)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(calls[-1][1], ["Start"])
        self.assertEqual(result.cleanup_result["released"], ["Start"])


if __name__ == "__main__":
    unittest.main()
