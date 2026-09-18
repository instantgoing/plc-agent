import os
import unittest
from pathlib import Path

from plc_tools import compile_st, start_plc, stop_plc, verify_file


@unittest.skipUnless(
    os.environ.get("PLC_OPENPLC_INTEGRATION") == "1",
    "set PLC_OPENPLC_INTEGRATION=1 with the real M2-M4 container running",
)
class RealVerifyIntegrationTests(unittest.TestCase):
    root = Path(__file__).parents[1]

    def test_problem_001_plan_passes_real_runtime(self) -> None:
        compiled = compile_st(self.root / "examples" / "problem_001_solution.st")
        self.assertTrue(compiled.success, compiled.to_dict())
        started = start_plc()
        self.assertTrue(started.success, started.to_dict())
        try:
            result = verify_file(self.root / "problems" / "problem_001" / "tests.json")
            self.assertTrue(result.passed, result.to_dict())
            self.assertEqual(len(result.steps), 3)
        finally:
            stop_plc()


if __name__ == "__main__":
    unittest.main()
