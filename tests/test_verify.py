import unittest
from unittest.mock import patch

from plc_tools.runtime import RuntimeResult
from plc_tools.variables import ForceVariablesResult, ReadVariablesResult, VariableValue
from plc_tools.verify import verify_plan


class VerifyContractTests(unittest.TestCase):
    def test_invalid_plan_is_structured_failure(self) -> None:
        result = verify_plan({"not_steps": []})
        self.assertFalse(result.passed)
        self.assertIn("steps", result.tool_error or "")

    @patch("plc_tools.verify.get_plc_status")
    @patch("plc_tools.verify.force_variables")
    @patch("plc_tools.verify.read_variables")
    def test_expected_actual_mismatch_is_reported(
        self, read_mock, force_mock, status_mock
    ) -> None:
        status_mock.return_value = RuntimeResult(True, None, "RUNNING", "")
        force_mock.return_value = ForceVariablesResult(True, {"start": True}, [], [])
        read_mock.return_value = ReadVariablesResult(
            True, {"motor": VariableValue(False, "BOOL", 1, "%QX0.0")}, []
        )

        result = verify_plan(
            [{"inputs": {"Start": True}, "expected": {"Motor": True}, "settle_ms": 0}]
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failures[0].variable, "Motor")
        self.assertTrue(result.failures[0].expected)
        self.assertFalse(result.failures[0].actual)
        self.assertTrue(force_mock.call_args_list[-1].kwargs["release"])


if __name__ == "__main__":
    unittest.main()
