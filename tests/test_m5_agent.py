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


class SequenceModel(Model):
    def __init__(self):
        super().__init__(model_id="unit-test-model")
        self.calls = 0

    def generate(self, messages, stop_sequences=None, tools_to_call_from=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            arguments = {"st_code": VALID_ST, "verification_plan": VALID_PLAN, "summary": "candidate"}
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="submit candidate",
                tool_calls=[
                    ChatMessageToolCall(
                        id="candidate-1",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="evaluate_candidate", arguments=arguments
                        ),
                    )
                ],
            )
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="verified",
            tool_calls=[
                ChatMessageToolCall(
                    id="final-1",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name="final_answer", arguments={"answer": "verified"}
                    ),
                )
            ],
        )


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
        self.assertEqual(model.calls, 2)

    def test_missing_real_model_configuration_is_not_mocked(self) -> None:
        result = PLCRepairAgent().run(M5Request("control a motor", 1))
        self.assertFalse(result.success)
        self.assertEqual(result.failure_kind, "model_unavailable")


if __name__ == "__main__":
    unittest.main()
