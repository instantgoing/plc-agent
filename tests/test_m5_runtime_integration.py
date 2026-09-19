import json
import os
import unittest
from pathlib import Path

from agent.tools import CandidateEvaluator


_ENABLED = os.getenv("PLC_M5_RUNTIME_INTEGRATION") == "1" and os.getenv("PLC_OPENPLC_INTEGRATION") == "1"


@unittest.skipUnless(
    _ENABLED,
    "set PLC_M5_RUNTIME_INTEGRATION=1 and PLC_OPENPLC_INTEGRATION=1 with the real runtime configured",
)
class RealM5RuntimeIntegrationTests(unittest.TestCase):
    def test_candidate_evaluator_passes_real_problem_001(self) -> None:
        root = Path(__file__).parents[1]
        source = root / "examples" / "problem_001_solution.st"
        plan = json.loads((root / "problems" / "problem_001" / "tests.json").read_text(encoding="utf-8"))
        evaluator = CandidateEvaluator(max_attempts=1, source_filename="candidate.st")
        result = evaluator.evaluate(source.read_text(encoding="utf-8"), {"steps": plan})
        self.assertTrue(result["accepted"], result)
        self.assertTrue(result["verify_result"]["passed"])
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
