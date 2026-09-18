import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plc_tools.check import _parse_diagnostics, check_st


class CheckContractTests(unittest.TestCase):
    def test_missing_source_is_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = check_st(Path(directory) / "missing.st")

        self.assertFalse(result.success)
        self.assertEqual(result.errors, [])
        self.assertIsNotNone(result.tool_error)

    def test_example_is_st(self) -> None:
        source = Path(__file__).parents[1] / "examples" / "minimal.st"
        self.assertIn("PROGRAM Main", source.read_text(encoding="utf-8"))

    def test_missing_compiler_is_a_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "program.st"
            source.write_text("PROGRAM Main\nEND_PROGRAM\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "PLC_MATIEC_BACKEND": "local",
                    "PLC_MATIEC_BIN": "definitely-not-a-real-iec2c",
                },
                clear=False,
            ):
                result = check_st(source)

        self.assertFalse(result.success)
        self.assertEqual(result.errors, [])
        self.assertIn("not found", result.tool_error or "")

    def test_public_result_does_not_expose_runtime_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = check_st(Path(directory) / "missing.st")

        self.assertNotIn("command", result.to_dict())

    def test_real_matiec_range_diagnostic_is_structured(self) -> None:
        st_code = "PROGRAM Main\nMotor := ;\nEND_PROGRAM\n"
        output = "program.st:2-10..2-10: error: unexpected token ';'\n"

        diagnostics = _parse_diagnostics(output, st_code)

        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].line, 2)
        self.assertEqual(diagnostics[0].column, 10)
        self.assertEqual(diagnostics[0].end_line, 2)
        self.assertEqual(diagnostics[0].end_column, 10)
        self.assertEqual(diagnostics[0].severity, "error")
        self.assertEqual(diagnostics[0].message, "unexpected token ';'")
        self.assertEqual(diagnostics[0].source_line, "Motor := ;")

    def test_alternate_range_format_and_public_filename(self) -> None:
        output = "/mnt/d/internal/program.st:3:2-3:7: warning: example warning"

        diagnostics = _parse_diagnostics(
            output, "one\ntwo\nthree", source_name="program.st"
        )

        self.assertEqual(diagnostics[0].file, "program.st")
        self.assertEqual(diagnostics[0].column, 2)
        self.assertEqual(diagnostics[0].end_column, 7)
        self.assertEqual(diagnostics[0].severity, "warning")

    def test_non_diagnostic_stdout_is_not_a_warning(self) -> None:
        self.assertEqual(_parse_diagnostics("POUS.c\nVARIABLES.csv\n", ""), [])


if __name__ == "__main__":
    unittest.main()
