import unittest
from unittest.mock import patch

from agent import M5Request, PLCRepairAgent
from agent._smolagents import (
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
    Model,
)
from plc_tools.check import CheckResult
from plc_tools.runtime import RuntimeResult
from plc_tools.verify import VerifyResult


VALID_ST = "PROGRAM Main\nEND_PROGRAM\n"
VALID_PLAN = {"steps": [{"inputs": {"Start": False}, "expected": {"Motor": False}}]}
VALID_SPEC = {
    "goal": "Control a motor from a Start input.",
    "inputs": ["Start at %IX0.0"],
    "outputs": ["Motor at %QX0.0"],
    "timing_rules": [],
    "state_rules": ["Motor follows Start"],
    "safety_rules": ["Motor is off when Start is false"],
    "observable_assertions": ["Start=false makes Motor=false"],
    "assumptions": [],
    "open_questions": [],
}


class SequenceModel(Model):
    def __init__(self):
        super().__init__(model_id="unit-test-model")
        self.calls = 0

    def generate(self, messages, stop_sequences=None, tools_to_call_from=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            name = "submit_requirement_spec"
            arguments = VALID_SPEC
        elif self.calls == 2:
            arguments = {"st_code": VALID_ST, "verification_plan": VALID_PLAN, "summary": "candidate"}
            name = "validate_candidate"
        elif self.calls == 3:
            arguments = {"st_code": VALID_ST, "verification_plan": VALID_PLAN, "summary": "candidate"}
            name = "evaluate_candidate"
        else:
            arguments = {"answer": "verified"}
            name = "final_answer"
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=name,
            tool_calls=[
                ChatMessageToolCall(
                    id=f"action-{self.calls}",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name=name, arguments=arguments
                    ),
                )
            ],
        )


class ActionSequenceModel(Model):
    def __init__(self, actions):
        super().__init__(model_id="unit-test-model")
        self.actions = list(actions)
        self.calls = 0

    def generate(self, messages, stop_sequences=None, tools_to_call_from=None, **kwargs):
        self.calls += 1
        name, arguments = self.actions.pop(0)
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=name,
            tool_calls=[
                ChatMessageToolCall(
                    id=f"action-{self.calls}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                )
            ],
        )


class AuthenticationErrorModel(Model):
    def __init__(self):
        super().__init__(model_id="unit-test-model")

    def generate(self, messages, stop_sequences=None, tools_to_call_from=None, **kwargs):
        raise RuntimeError("Error code: 401 - Authentication failed for API key")


class M5AgentTests(unittest.TestCase):
    def test_custom_agent_accepts_only_verified_candidate(self) -> None:
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        check = CheckResult(True, [], [])
        verify = VerifyResult(True, [], [])
        compile_result = type("Compile", (), {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}})()
        model = SequenceModel()
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.check_st_text", return_value=check
        ), patch("agent.tools.compile_st", return_value=compile_result), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=verify), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            result = PLCRepairAgent(model=model).run(M5Request("control a motor", 3))

        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.attempts[0].phase, "accepted")
        self.assertEqual(model.calls, 4)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.final_message, "verified")
        self.assertEqual(result.requirement_spec, VALID_SPEC)

    def test_agent_can_pause_for_required_user_input_without_running_plc(self) -> None:
        question = "Which addresses should Start, Stop, and Motor use?"
        choices = [
            "Momentary normally-open buttons; I will supply the actual addresses.",
            "I will provide the real addresses and button wiring.",
        ]
        model = ActionSequenceModel(
            [
                (
                    "submit_requirement_spec",
                    {
                        "goal": "Control a motor with Start and Stop.",
                        "inputs": [],
                        "outputs": [],
                        "timing_rules": [],
                        "state_rules": [],
                        "safety_rules": [],
                        "observable_assertions": [],
                        "assumptions": [],
                        "open_questions": [question],
                    },
                ),
                ("ask_user", {"question": question, "choices": choices}),
                ("final_answer", {"answer": question}),
            ]
        )

        result = PLCRepairAgent(model=model).run(M5Request("build a motor controller"))

        self.assertFalse(result.success)
        self.assertIsNone(result.failure_kind)
        self.assertEqual(result.state, "needs_user_input")
        self.assertEqual(result.final_message, question)
        self.assertEqual(result.attempts, [])
        self.assertEqual(result.requirement_spec["open_questions"], [question])
        self.assertEqual(result.clarification_options, choices)

    def test_unconfirmed_io_addresses_are_not_offered_as_choices(self) -> None:
        question = "What are the actual Start and Motor I/O addresses?"
        model = ActionSequenceModel([
            ("submit_requirement_spec", {
                **VALID_SPEC,
                "inputs": [],
                "outputs": [],
                "observable_assertions": [],
                "open_questions": [question],
            }),
            ("ask_user", {"question": question, "choices": [
                "Use Start=%IX0.0 and Motor=%QX0.0.",
                "I will supply the actual addresses.",
            ]}),
            ("final_answer", {"answer": "Guess Start=%IX0.0 and Motor=%QX0.0."}),
        ])

        result = PLCRepairAgent(model=model).run(M5Request("control a motor"))

        self.assertEqual(result.state, "needs_user_input")
        self.assertEqual(result.final_message, question)
        self.assertEqual(result.clarification_options, ["I will supply the actual addresses."])

    def test_agent_can_report_an_unverifiable_requirement(self) -> None:
        reason = "The requested internal timing property has no observable PLC output."
        model = ActionSequenceModel(
            [
                ("report_unverifiable", {"reason": reason}),
                ("final_answer", {"answer": reason}),
            ]
        )

        result = PLCRepairAgent(model=model).run(M5Request("prove an internal property"))

        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "unverifiable_requirement")
        self.assertEqual(result.state, "unverifiable")
        self.assertEqual(result.final_message, reason)
        self.assertEqual(result.attempts, [])

    def test_agent_can_report_a_safe_non_success_outcome(self) -> None:
        reason = "The requirement is internally contradictory, so generation was stopped."
        model = ActionSequenceModel(
            [
                ("report_failure", {"reason": reason}),
                ("final_answer", {"answer": reason}),
            ]
        )

        result = PLCRepairAgent(model=model).run(M5Request("build contradictory behavior"))

        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "agent_reported_failure")
        self.assertEqual(result.state, "fatal_failure")
        self.assertEqual(result.final_message, reason)
        self.assertEqual(result.attempts, [])

    def test_invalid_submission_does_not_spend_the_runtime_attempt(self) -> None:
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                (
                    "validate_candidate",
                    {"st_code": VALID_ST, "verification_plan": {"steps": []}},
                ),
                (
                    "validate_candidate",
                    {"st_code": VALID_ST, "verification_plan": VALID_PLAN},
                ),
                (
                    "evaluate_candidate",
                    {"st_code": VALID_ST, "verification_plan": VALID_PLAN},
                ),
                ("final_answer", {"answer": "verified after correcting the plan"}),
            ]
        )
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        compile_result = type(
            "Compile",
            (),
            {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}},
        )()
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.check_st_text", return_value=CheckResult(True, [], [])
        ), patch("agent.tools.compile_st", return_value=compile_result), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=VerifyResult(True, [], [])), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            result = PLCRepairAgent(model=model).run(
                M5Request("control a motor", max_attempts=1, max_actions=6)
            )

        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.final_message, "verified after correcting the plan")

    def test_last_failed_candidate_reaches_exhausted_terminal_state(self) -> None:
        final_message = "Behavior verification failed and the candidate budget is exhausted."
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                (
                    "validate_candidate",
                    {"st_code": VALID_ST, "verification_plan": VALID_PLAN},
                ),
                (
                    "evaluate_candidate",
                    {"st_code": VALID_ST, "verification_plan": VALID_PLAN},
                ),
                ("final_answer", {"answer": final_message}),
            ]
        )
        runtime = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        started = RuntimeResult(True, "RUNNING", "RUNNING", "ok")
        stopped = RuntimeResult(True, "STOPPED", "STOPPED", "ok")
        compile_result = type(
            "Compile",
            (),
            {"success": True, "tool_error": None, "to_dict": lambda self: {"success": True}},
        )()
        with patch("agent.tools.get_plc_status", return_value=runtime), patch(
            "agent.tools.check_st_text", return_value=CheckResult(True, [], [])
        ), patch("agent.tools.compile_st", return_value=compile_result), patch(
            "agent.tools.start_plc", return_value=started
        ), patch("agent.tools.verify_plan", return_value=VerifyResult(False, [], [])), patch(
            "agent.tools.stop_plc", return_value=stopped
        ):
            result = PLCRepairAgent(model=model).run(
                M5Request("control a motor", max_attempts=1, max_actions=5)
            )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "attempt_limit_reached")
        self.assertEqual(result.state, "exhausted")
        self.assertIn("exhausted", result.final_message)
        self.assertEqual(result.model_final_message, final_message)
        self.assertEqual(len(result.attempts), 1)

    def test_action_budget_exhaustion_is_distinct_from_candidate_exhaustion(self) -> None:
        model = ActionSequenceModel(
            [
                ("final_answer", {"answer": "unverified"}),
                ("final_answer", {"answer": "still unverified"}),
                ("fallback after action limit", {}),
            ]
        )

        result = PLCRepairAgent(model=model).run(
            M5Request("control a motor", max_attempts=3, max_actions=2)
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "action_limit_reached")
        self.assertEqual(result.state, "exhausted")
        self.assertEqual(result.attempts, [])

    def test_authentication_error_is_classified_before_any_plc_attempt(self) -> None:
        result = PLCRepairAgent(model=AuthenticationErrorModel()).run(
            M5Request("control a motor")
        )

        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "model_authentication_failed")
        self.assertEqual(result.state, "fatal_failure")
        self.assertEqual(result.attempts, [])

    def test_model_failures_have_actionable_categories(self) -> None:
        cases = {
            "connection timed out": "model_connection_failed",
            "maximum context length exceeded": "model_context_exceeded",
            "tool_choice is unsupported": "model_tool_unsupported",
            "could not parse tool call JSON": "model_output_invalid",
            "provider unavailable": "model_unavailable",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(
                    PLCRepairAgent._classify_model_error(RuntimeError(message)),
                    expected,
                )

    def test_missing_real_model_configuration_is_not_mocked(self) -> None:
        result = PLCRepairAgent().run(M5Request("control a motor", 1))
        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "model_unavailable")


if __name__ == "__main__":
    unittest.main()
