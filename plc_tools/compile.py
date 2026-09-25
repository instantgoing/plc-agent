"""Stable M2 contracts for compiling and loading Structured Text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from plc_tools.check import Diagnostic, _parse_diagnostics
from plc_tools.state import VariableEntry, parse_variable_map, save_variable_map
from runtime.openplc import (
    OpenPLCConfigurationError,
    compile_program,
    upload_program,
)


CompileStage = Literal[
    "iec2c",
    "xml2st_debug",
    "xml2st_gluevars",
    "package",
    "upload",
    "gcc",
]


@dataclass(frozen=True)
class CompileResult:
    success: bool
    failed_stage: CompileStage | None
    errors: list[Diagnostic]
    warnings: list[Diagnostic]
    generated_files: list[str]
    runtime_compile_status: str | None
    runtime_logs: list[str]
    variables: list[VariableEntry]
    tool_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "failed_stage": self.failed_stage,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
            "generated_files": self.generated_files,
            "runtime_compile_status": self.runtime_compile_status,
            "runtime_logs": self.runtime_logs,
            "variables": [asdict(item) for item in self.variables],
            "tool_error": self.tool_error,
        }


def _tool_failure(message: str) -> CompileResult:
    return CompileResult(False, None, [], [], [], None, [], [], message)


def compile_st(source_path: str | Path, *, timeout: float = 90.0) -> CompileResult:
    """Compile ST, upload it, and wait for the Runtime's real GCC result."""

    source = Path(source_path).resolve()
    if not source.is_file():
        return _tool_failure(f"ST source does not exist: {source}")
    try:
        st_code = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return _tool_failure(f"cannot read ST source as UTF-8: {exc}")

    try:
        compiled = compile_program(source, timeout=timeout)
    except OpenPLCConfigurationError as exc:
        return _tool_failure(str(exc))

    diagnostics = _parse_diagnostics(
        "\n".join(part for part in (compiled.stderr, compiled.stdout) if part),
        st_code,
        source_name=source.name,
    )
    errors = [item for item in diagnostics if item.severity == "error"]
    warnings = [item for item in diagnostics if item.severity == "warning"]
    if not compiled.success:
        if compiled.failed_stage == "iec2c" and not errors:
            errors = [
                Diagnostic(
                    message=(compiled.stderr.strip() or "MatIEC compilation failed")[:4000],
                    severity="error",
                )
            ]
        return CompileResult(
            False,
            compiled.failed_stage,
            errors,
            warnings,
            [],
            None,
            [],
            [],
        )

    variables = parse_variable_map(compiled.variables_csv, st_code,
                                   fragment_fallback=False)

    try:
        uploaded = upload_program(compiled.package_path, timeout=timeout)
    except OpenPLCConfigurationError as exc:
        return _tool_failure(str(exc))

    if not uploaded.success:
        return CompileResult(
            False,
            uploaded.failed_stage,
            errors,
            warnings,
            compiled.generated_files,
            uploaded.status,
            uploaded.logs,
            variables,
            uploaded.error,
        )
    save_variable_map(variables)
    return CompileResult(
        True,
        None,
        errors,
        warnings,
        compiled.generated_files,
        uploaded.status,
        uploaded.logs,
        variables,
    )
