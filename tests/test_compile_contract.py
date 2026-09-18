import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plc_tools.compile import compile_st
from runtime.openplc import ContainerCompileResult, UploadResult


class CompileContractTests(unittest.TestCase):
    def test_missing_source_is_structured_tool_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = compile_st(Path(directory) / "missing.st")

        self.assertFalse(result.success)
        self.assertIsNone(result.failed_stage)
        self.assertIn("does not exist", result.tool_error or "")

    def test_real_compiler_diagnostic_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "program.st"
            source.write_text("PROGRAM Main\nMotor := ;\nEND_PROGRAM\n", encoding="utf-8")
            compiled = ContainerCompileResult(
                False,
                "iec2c",
                None,
                [],
                "",
                "program.st:2-10..2-10: error: unexpected token ';'",
            )
            with patch("plc_tools.compile.compile_program", return_value=compiled):
                result = compile_st(source)

        self.assertFalse(result.success)
        self.assertEqual(result.failed_stage, "iec2c")
        self.assertEqual(result.errors[0].line, 2)
        self.assertEqual(result.errors[0].source_line, "Motor := ;")

    def test_success_requires_runtime_gcc_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "program.st"
            source.write_text("PROGRAM Main\nEND_PROGRAM\n", encoding="utf-8")
            compiled = ContainerCompileResult(
                True, None, "/tmp/program.zip", ["Config0.c"], "", ""
            )
            uploaded = UploadResult(
                False, "gcc", "FAILED", ["error: link failed"], "Runtime GCC compilation failed"
            )
            with patch("plc_tools.compile.compile_program", return_value=compiled), patch(
                "plc_tools.compile.upload_program", return_value=uploaded
            ):
                result = compile_st(source)

        self.assertFalse(result.success)
        self.assertEqual(result.failed_stage, "gcc")
        self.assertEqual(result.runtime_compile_status, "FAILED")


if __name__ == "__main__":
    unittest.main()
