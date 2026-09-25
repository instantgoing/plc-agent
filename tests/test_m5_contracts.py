import unittest

from agent.contracts import AgentControlState, M5Request, M5Result, RequirementSpec


class M5ContractTests(unittest.TestCase):
    def test_requirement_spec_distinguishes_ready_from_open_questions(self) -> None:
        incomplete = RequirementSpec(
            goal="Control a motor",
            open_questions=["Which output address controls the motor?"],
        )
        self.assertFalse(incomplete.ready)
        self.assertEqual(incomplete.validation_errors(), [])

        complete = RequirementSpec(
            goal="Control a motor",
            outputs=["Motor at %QX0.0"],
            observable_assertions=["Motor turns off when Stop is true"],
        )
        self.assertTrue(complete.ready)

    def test_requirement_spec_requires_observable_behavior_when_ready(self) -> None:
        spec = RequirementSpec(goal="Control a motor")
        self.assertFalse(spec.ready)
        self.assertIn("outputs must identify", " ".join(spec.validation_errors()))

    def test_request_accepts_bounded_attempts(self) -> None:
        self.assertIsNone(M5Request("make a motor controller", 3).validate())

    def test_request_rejects_unbounded_attempts(self) -> None:
        self.assertIn("between 1 and 3", M5Request("task", 4).validate() or "")

    def test_request_has_a_separate_bounded_action_budget(self) -> None:
        self.assertIsNone(M5Request("task", max_attempts=3, max_actions=8).validate())
        self.assertIn(
            "between 2 and 12",
            M5Request("task", max_attempts=3, max_actions=13).validate() or "",
        )

    def test_terminal_state_cannot_return_to_evaluation(self) -> None:
        control = AgentControlState()
        control.transition("needs_user_input", message="Which input address should be used?")
        self.assertTrue(control.terminal)
        with self.assertRaises(ValueError):
            control.transition("candidate_ready")

    def test_result_is_json_compatible_and_has_no_secret_field(self) -> None:
        result = M5Result(
            success=False,
            failure_kind="model_unavailable",
            st_code=None,
            verification_plan=None,
            attempts=[],
            final_message="missing credentials",
            model=None,
            state="fatal_failure",
        )
        payload = result.to_dict()
        self.assertEqual(payload["failure_kind"], "model_unavailable")
        self.assertEqual(payload["state"], "fatal_failure")
        self.assertNotIn("api_key", payload)


if __name__ == "__main__":
    unittest.main()
