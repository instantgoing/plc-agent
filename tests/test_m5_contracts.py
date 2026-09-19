import unittest

from agent.contracts import M5Request, M5Result


class M5ContractTests(unittest.TestCase):
    def test_request_accepts_bounded_attempts(self) -> None:
        self.assertIsNone(M5Request("make a motor controller", 3).validate())

    def test_request_rejects_unbounded_attempts(self) -> None:
        self.assertIn("between 1 and 3", M5Request("task", 4).validate() or "")

    def test_result_is_json_compatible_and_has_no_secret_field(self) -> None:
        result = M5Result(
            success=False,
            failure_kind="model_unavailable",
            st_code=None,
            verification_plan=None,
            attempts=[],
            final_message="missing credentials",
            model=None,
        )
        payload = result.to_dict()
        self.assertEqual(payload["failure_kind"], "model_unavailable")
        self.assertNotIn("api_key", payload)


if __name__ == "__main__":
    unittest.main()
