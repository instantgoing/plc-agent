import os
import time
import unittest
from pathlib import Path

from plc_tools import compile_st, force_variables, read_variables, start_plc, stop_plc


@unittest.skipUnless(
    os.environ.get("PLC_OPENPLC_INTEGRATION") == "1",
    "set PLC_OPENPLC_INTEGRATION=1 with the real M2/M3 container running",
)
class RealVariableIntegrationTests(unittest.TestCase):
    root = Path(__file__).parents[1]

    def test_force_input_scan_and_read_output(self) -> None:
        compiled = compile_st(self.root / "tests" / "fixtures" / "m3_motor_follow.st")
        self.assertTrue(compiled.success, compiled.to_dict())
        self.assertEqual([item.name for item in compiled.variables], ["start", "motor"])
        started = start_plc()
        self.assertTrue(started.success, started.to_dict())

        try:
            cleared = force_variables({"Start": False})
            self.assertTrue(cleared.success, cleared.to_dict())
            time.sleep(0.05)

            initial = read_variables(["Start", "Motor"])
            self.assertTrue(initial.success, initial.to_dict())
            self.assertFalse(initial.variables["start"].value)
            self.assertFalse(initial.variables["motor"].value)

            forced = force_variables({"Start": True})
            self.assertTrue(forced.success, forced.to_dict())
            time.sleep(0.05)

            observed = read_variables(["Start", "Motor"])
            self.assertTrue(observed.success, observed.to_dict())
            self.assertTrue(observed.variables["start"].value)
            self.assertTrue(observed.variables["motor"].value)
            self.assertIsNotNone(observed.tick)
        finally:
            force_variables({"Start": False})
            time.sleep(0.05)
            force_variables(release=["Start"])
            stop_plc()


if __name__ == "__main__":
    unittest.main()
