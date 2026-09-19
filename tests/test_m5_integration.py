import os
import unittest

from agent import M5Request, PLCRepairAgent


_M5_REAL_ENV = os.getenv("PLC_AGENT_INTEGRATION") == "1"
_RUNTIME_ENV = os.getenv("PLC_OPENPLC_INTEGRATION") == "1"
_MODEL_ENV = bool(os.getenv("PLC_AGENT_API_KEY") and os.getenv("PLC_AGENT_MODEL_ID"))


@unittest.skipUnless(
    _M5_REAL_ENV and _RUNTIME_ENV and _MODEL_ENV,
    "set PLC_AGENT_INTEGRATION=1, PLC_OPENPLC_INTEGRATION=1, PLC_AGENT_API_KEY, and PLC_AGENT_MODEL_ID",
)
class RealM5IntegrationTests(unittest.TestCase):
    def test_real_llm_generates_and_verifies_problem_001(self) -> None:
        task = (
            "Implement a PLC motor start/stop controller. Use located BOOL inputs "
            "Start at %IX0.0 and Stop at %IX0.1, and located BOOL output Motor at "
            "%QX0.0. When Start is true and Stop is false Motor must be true. "
            "When Stop is true Motor must be false. Include a complete executable "
            "Structured Text program and behavior checks for the important cases."
        )
        result = PLCRepairAgent().run(M5Request(task=task, max_attempts=3))
        self.assertTrue(result.success, result.to_dict())
        self.assertTrue(result.attempts)
        self.assertTrue(result.attempts[-1].accepted)
        self.assertEqual(result.attempts[-1].verify_result["passed"], True)


if __name__ == "__main__":
    unittest.main()
