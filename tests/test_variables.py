import unittest

from plc_tools.state import parse_variable_map
from plc_tools.variables import (
    _build_force_command,
    _build_read_command,
    _parse_read_response,
    _serialize,
)


class VariableContractTests(unittest.TestCase):
    def test_matiec_csv_maps_debug_indices_and_at_locations(self) -> None:
        raw = """0;FB;CONFIG0.RES0.INST0;CONFIG0.RES0.INST0;MAIN;;0;
1;IN;CONFIG0.RES0.INST0.START;CONFIG0.RES0.INST0.START;BOOL;BOOL;0;
2;OUT;CONFIG0.RES0.INST0.MOTOR;CONFIG0.RES0.INST0.MOTOR;BOOL;BOOL;0;
"""
        st = "Start AT %IX0.0 : BOOL;\nMotor AT %QX0.0 : BOOL;"

        variables = parse_variable_map(raw, st)

        self.assertEqual([item.name for item in variables], ["start", "motor"])
        self.assertEqual([item.index for item in variables], [0, 1])
        self.assertEqual([item.location for item in variables], ["%IX0.0", "%QX0.0"])

    def test_debug_commands_match_openplc_wire_format(self) -> None:
        self.assertEqual(_build_read_command([0, 258]), "44 00 02 00 00 01 02")
        self.assertEqual(_build_force_command(1, 1, b"\x01"), "42 00 01 01 00 01 01")

    def test_bool_snapshot_decodes_with_runtime_tick(self) -> None:
        variables = parse_variable_map(
            "1;IN;CONFIG0.RES0.INST0.START;x;BOOL;BOOL;0;\n"
            "2;OUT;CONFIG0.RES0.INST0.MOTOR;x;BOOL;BOOL;0;\n",
            "Start AT %IX0.0 : BOOL;\nMotor AT %QX0.0 : BOOL;",
        )
        tick, values = _parse_read_response(
            "44 7E 00 01 00 00 00 2A 00 02 01 00", variables
        )

        self.assertEqual(tick, 42)
        self.assertTrue(values["start"].value)
        self.assertFalse(values["motor"].value)

    def test_bool_serialization_rejects_ambiguous_text(self) -> None:
        self.assertEqual(_serialize("BOOL", "true"), b"\x01")
        self.assertEqual(_serialize("BOOL", "false"), b"\x00")
        self.assertIsNone(_serialize("BOOL", "yes"))


if __name__ == "__main__":
    unittest.main()
