import os
import unittest
from pathlib import Path

from plc_tools import check_st


@unittest.skipUnless(
    os.environ.get("PLC_MATIEC_INTEGRATION") == "1",
    "set PLC_MATIEC_INTEGRATION=1 with a real MatIEC backend",
)
class RealMatiecIntegrationTests(unittest.TestCase):
    root = Path(__file__).parents[1]

    def test_valid_st_passes_real_matiec(self) -> None:
        result = check_st(self.root / "examples" / "minimal.st")

        self.assertTrue(result.success, result.to_dict())
        self.assertIsNone(result.tool_error)
        self.assertEqual(result.errors, [])

    def test_invalid_st_returns_line_and_range(self) -> None:
        result = check_st(self.root / "examples" / "invalid.st")

        self.assertFalse(result.success)
        self.assertIsNone(result.tool_error)
        self.assertGreaterEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].file, "invalid.st")
        self.assertEqual(result.errors[0].line, 6)
        self.assertIsNotNone(result.errors[0].column)
        self.assertEqual(result.errors[0].source_line, "Motor := ;")
