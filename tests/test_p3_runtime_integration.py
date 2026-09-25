"""Opt-in real Runtime acceptance for a context-guided FB interface edit."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from plc_tools.mcp_adapter import PLCMCPAdapter


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "p3_runtime"


@unittest.skipUnless(os.environ.get("PLC_OPENPLC_INTEGRATION") == "1",
                     "requires real MatIEC/OpenPLC test Runtime")
class Phase3RuntimeIntegrationTests(unittest.TestCase):
    def test_context_guided_fault_edit_and_real_verification(self):
        with tempfile.TemporaryDirectory(prefix="plc-p3-") as directory:
            workspace = Path(directory)
            source = workspace / "Motor.st"
            shutil.copyfile(FIXTURE / "Motor.st", source)
            shutil.copyfile(FIXTURE / "motor_fault.tests.json", workspace / "motor_fault.tests.json")
            adapter = PLCMCPAdapter(workspace)

            declaration = adapter.find_symbol("FB_Motor")
            references = adapter.find_references("FB_Motor")
            self.assertEqual(declaration["matches"][0]["kind"], "function_block")
            self.assertEqual(references["references"][0]["owner"], "MAIN")

            original = source.read_text(encoding="utf-8")
            updated = original.replace("    Stop : BOOL;", "    Stop : BOOL;\n    Fault : BOOL;")
            updated = updated.replace("Running := Start AND NOT Stop;",
                                      "Running := Start AND NOT Stop AND NOT Fault;")
            updated = updated.replace("MotorController(Start := StartPB, Stop := StopPB);",
                                      "MotorController(Start := StartPB, Stop := StopPB, Fault := FaultPB);")
            self.assertNotEqual(updated, original)
            source.write_text(updated, encoding="utf-8")
            self.assertEqual(adapter.find_symbol("FB_Motor.Fault")["total"], 1)

            checked = adapter.check("Motor.st")
            self.assertTrue(checked["success"], checked)
            compiled = adapter.compile("Motor.st")
            self.assertTrue(compiled["success"], compiled)
            started = adapter.start()
            self.assertTrue(started["success"], started)
            try:
                verified = adapter.verify("motor_fault.tests.json")
                self.assertTrue(verified["success"], verified)
                self.assertTrue(verified["passed"], verified)
                self.assertEqual(len(verified["results"]), 5)
            finally:
                adapter.force({}, release=["StartPB", "StopPB", "FaultPB"])
                stopped = adapter.stop()
                self.assertTrue(stopped["success"], stopped)


if __name__ == "__main__":
    unittest.main()
