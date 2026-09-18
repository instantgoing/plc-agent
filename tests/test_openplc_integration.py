import os
import unittest
from pathlib import Path

from plc_tools import compile_st, start_plc, stop_plc


@unittest.skipUnless(
    os.environ.get("PLC_OPENPLC_INTEGRATION") == "1",
    "set PLC_OPENPLC_INTEGRATION=1 with the real M2 container running",
)
class RealOpenPLCIntegrationTests(unittest.TestCase):
    root = Path(__file__).parents[1]

    def test_compile_load_and_start_real_scan_cycle(self) -> None:
        compiled = compile_st(self.root / "examples" / "runtime_minimal.st")
        self.assertTrue(compiled.success, compiled.to_dict())
        self.assertEqual(compiled.runtime_compile_status, "SUCCESS")

        started = start_plc()
        self.assertTrue(started.success, started.to_dict())
        self.assertEqual(started.actual_status, "RUNNING")

        stopped = stop_plc()
        self.assertTrue(stopped.success, stopped.to_dict())


if __name__ == "__main__":
    unittest.main()
