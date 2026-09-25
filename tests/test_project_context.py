"""Static ST context contracts; source syntax is parsed by Tree-sitter."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plc_context import ProjectIndexer
from plc_context.st_adapter import parse_st


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class STAdapterTests(unittest.TestCase):
    def test_program_and_located_variables_have_source_locations(self):
        project = ProjectIndexer(FIXTURES / "p3_small").snapshot()
        self.assertTrue(project.complete, project.files)
        self.assertEqual([(p.name, p.kind) for p in project.pous], [("MAIN", "program")])
        variables = project.pous[0].variables
        self.assertEqual([(v.name, v.scope, v.address) for v in variables], [
            ("StartPB", "local", "%IX0.0"), ("Motor", "local", "%QX0.0")])
        self.assertEqual((variables[0].location.file, variables[0].location.line), ("Main.st", 3))
        self.assertTrue(variables[0].located)

    def test_functions_blocks_globals_scopes_and_calls(self):
        index = ProjectIndexer(FIXTURES / "p3_multi")
        project = index.snapshot()
        self.assertTrue(project.complete, project.files)
        self.assertEqual({p.kind for p in project.pous}, {"program", "function_block", "function"})
        page = index.project_context("pous", limit=1, offset=1)
        self.assertEqual((page["total"], len(page["items"])), (4, 1))
        self.assertNotIn("globals", page)
        motor = next(p for p in project.pous if p.name == "FB_Motor")
        self.assertEqual([(v.name, v.scope) for v in motor.variables], [
            ("Start", "input"), ("Stop", "input"), ("Running", "output")])
        self.assertEqual([v.name for v in project.globals], ["SystemReady"])
        self.assertEqual([(i.symbol, i.address, i.direction) for i in project.io if i.address == "%QX0.0"],
                         [("Motor", "%QX0.0", "output")])
        calls = {(r.owner, r.symbol) for r in project.references if r.type == "call"}
        self.assertTrue({("MAIN", "FB_Motor"), ("MAIN", "FB_Alarm"),
                         ("MAIN", "FC_Scale")} <= calls, calls)
        self.assertEqual(index.find_symbol("%QX0.0")["matches"][0]["name"], "Motor")
        self.assertEqual(index.find_symbol("FB_", match="prefix")["total"], 2)
        self.assertEqual(index.find_symbol("Scale", match="substring")["total"], 2)
        self.assertEqual(index.find_symbol("FB_Motor.Running")["matches"][0]["scope"], "output")
        member_refs = index.find_references("FB_Motor.Running")
        self.assertEqual([(r["owner"], r["type"]) for r in member_refs["references"] if r["owner"] == "MAIN"],
                         [("MAIN", "member")])
        references = index.find_references("FB_Motor")
        self.assertEqual(references["declarations"][0]["file"], "src/FB_Motor.st")
        self.assertEqual([(r["owner"], r["file"]) for r in references["references"]],
                         [("MAIN", "src/Main.st")])
        io_refs = index.find_references("%QX0.0")
        self.assertEqual(io_refs["declarations"][0]["name"], "Motor")
        self.assertTrue(any(r["owner"] == "MAIN" for r in io_refs["references"]))

    def test_broken_file_is_reported_without_losing_good_file(self):
        index = ProjectIndexer(FIXTURES / "p3_broken")
        project = index.snapshot()
        self.assertFalse(project.complete)
        self.assertEqual([p.name for p in project.pous], ["FB_Healthy"])
        broken = next(f for f in project.files if f.path == "Broken.st")
        self.assertFalse(broken.indexed)
        self.assertTrue(broken.diagnostics)
        self.assertEqual(index.find_symbol("FB_Healthy")["total"], 1)

    def test_comments_and_strings_are_not_declarations(self):
        source = b"PROGRAM MAIN\nVAR\n X : BOOL;\nEND_VAR\n// PROGRAM Fake\nX := TRUE;\nEND_PROGRAM\n"
        result = parse_st(source, "Memory.st")
        self.assertTrue(result.source_file.complete, result.source_file.diagnostics)
        self.assertEqual([p.name for p in result.pous], ["MAIN"])

    def test_remaining_scopes_constant_initializers_and_data_type(self):
        source = ("TYPE\nMotorState : BOOL;\nEND_TYPE\n"
                  "FUNCTION_BLOCK FB_Scope\n"
                  "VAR_IN_OUT\nShared : BOOL;\nEND_VAR\n"
                  "VAR_TEMP\nScratch : INT;\nEND_VAR\n"
                  "VAR_EXTERNAL\nSystemReady : BOOL;\nEND_VAR\n"
                  "VAR CONSTANT\nLimit : INT := 5;\nEND_VAR\n"
                  "END_FUNCTION_BLOCK\n")
        result = parse_st(source.encode(), "Scope.st")
        self.assertTrue(result.source_file.complete, result.source_file.diagnostics)
        self.assertEqual([item.name for item in result.data_types], ["MotorState"])
        self.assertEqual([(v.name, v.scope) for v in result.pous[0].variables], [
            ("Shared", "inout"), ("Scratch", "temporary"),
            ("SystemReady", "external"), ("Limit", "constant")])
        self.assertEqual(result.pous[0].variables[-1].initial_value, "5")

    def test_unsupported_syntax_marks_incomplete_without_invented_ast(self):
        result = parse_st(b"PROGRAM MAIN\nVENDOR_MAGIC X;\nEND_PROGRAM\n", "Vendor.st")
        self.assertFalse(result.source_file.complete)
        self.assertTrue(result.source_file.diagnostics)
        self.assertTrue(result.source_file.unsupported_constructs)
        self.assertEqual(result.pous, ())

    def test_refreshes_only_changed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(FIXTURES / "p3_multi" / "src", root / "src")
            index = ProjectIndexer(root)
            first = index.snapshot()
            initial_count = index.parse_count
            self.assertEqual(initial_count, 5)
            self.assertIs(index.snapshot(), first)
            self.assertEqual(index.parse_count, initial_count)
            path = root / "src" / "FB_Motor.st"
            path.write_text(path.read_text(encoding="utf-8").replace("Running : BOOL", "MotorRunning : BOOL"),
                            encoding="utf-8")
            refreshed = index.snapshot()
            self.assertIsNot(refreshed, first)
            self.assertEqual(index.parse_count, initial_count + 1)
            self.assertEqual(index.find_symbol("MotorRunning")["total"], 1)
            path.unlink()
            self.assertEqual(index.find_symbol("FB_Motor")["total"], 0)

    def test_parser_exception_isolated_to_one_file(self):
        from plc_context.st_adapter import parse_st as real_parse

        def parse(source, file):
            if file == "Broken.st":
                raise RuntimeError("parser failed")
            return real_parse(source, file)

        with patch("plc_context.indexer.parse_st", side_effect=parse):
            index = ProjectIndexer(FIXTURES / "p3_broken")
            snapshot = index.snapshot()
        self.assertFalse(snapshot.complete)
        self.assertEqual([p.name for p in snapshot.pous], ["FB_Healthy"])
        self.assertIn("parser failed", snapshot.files[0].diagnostics[0].message)

    def test_address_references_do_not_mix_same_named_variables(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for owner, address, value in (("A", "%QX0.0", "TRUE"),
                                          ("B", "%QX0.1", "FALSE")):
                (root / f"{owner}.st").write_text(
                    f"PROGRAM {owner}\nVAR\nMotor AT {address} : BOOL;\nEND_VAR\n"
                    f"Motor := {value};\nEND_PROGRAM\n", encoding="utf-8")
            index = ProjectIndexer(root)
            result = index.find_references("%QX0.0")
            self.assertEqual([(r["owner"], r["line"]) for r in result["references"]],
                             [("A", 5)])


if __name__ == "__main__":
    unittest.main()
