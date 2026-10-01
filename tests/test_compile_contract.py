import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from plc_tools.compile import compile_st
from runtime.openplc import ContainerCompileResult, UploadResult


class CompileContractTests(unittest.TestCase):
    def setUp(self):
        self.state_directory = tempfile.TemporaryDirectory()
        self.state_env = patch.dict(os.environ, {"PLC_STATE_FILE": str(Path(self.state_directory.name) / "state.json")})
        self.state_env.start()

    def tearDown(self):
        self.state_env.stop()
        self.state_directory.cleanup()

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

    def test_compile_does_not_upload_after_force_cleanup_failure(self):
        from plc_tools.state import save_variable_map, record_forces
        from plc_tools.variables import ForceVariablesResult
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'program.st'
            source.write_text('PROGRAM MAIN\nEND_PROGRAM\n', encoding='utf-8')
            save_variable_map([])
            record_forces({'main:start': True}, [])
            compiled = ContainerCompileResult(True, None, '/tmp/program.zip', [], '', '')
            with patch('plc_tools.compile.compile_program', return_value=compiled), patch('plc_tools.variables._force_variables', return_value=ForceVariablesResult(False, {}, [], [], 'offline')), patch('plc_tools.compile.upload_program') as upload:
                result = compile_st(source)
            self.assertFalse(result.success)
            self.assertIn('releasing known forces', result.tool_error)
            upload.assert_not_called()

    def test_mid_compile_source_edit_invalidates_debug_map(self):
        from plc_tools.state import load_debug_state
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'program.st'
            source.write_text('PROGRAM MAIN\nEND_PROGRAM\n', encoding='utf-8')
            compiled = ContainerCompileResult(True, None, '/tmp/program.zip', [], '', '')
            def upload(*args, **kwargs):
                source.write_text('PROGRAM MAIN\n(* changed *)\nEND_PROGRAM\n', encoding='utf-8')
                return UploadResult(True, None, 'SUCCESS', [], None)
            with patch('plc_tools.compile.compile_program', return_value=compiled), patch('plc_tools.compile.upload_program', side_effect=upload):
                result = compile_st(source)
            self.assertFalse(result.success)
            self.assertIsNone(load_debug_state().get('program'))


if __name__ == "__main__":
    unittest.main()
