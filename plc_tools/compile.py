"""Stable M2 contracts for compiling and loading Structured Text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from plc_tools.check import Diagnostic, _parse_diagnostics
from plc_tools.state import VariableEntry, parse_variable_map, save_variable_map, program_identity, serialized_debug, load_debug_state
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


@serialized_debug
def compile_st(source_path: str | Path, *, timeout: float = 90.0) -> CompileResult:
    """Compile ST, upload it, and wait for the Runtime's real GCC result."""

    source = Path(source_path).resolve()
    if not source.is_file():
        return _tool_failure(f"ST source does not exist: {source}")
    try:
        source_bytes = source.read_bytes()
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
        known = list(load_debug_state().get("forced", {}))
        if known:
            from plc_tools.variables import _force_variables
            cleanup = _force_variables({}, release=known)
            if not cleanup.success:
                return _tool_failure("cannot replace program before releasing known forces: " +
                                     (cleanup.tool_error or "; ".join(f.reason for f in cleanup.failures)))
        # Upload failure may already have replaced the runtime program. Fail
        # closed until a complete successful build establishes a new identity.
        save_variable_map([])
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
    try:
        if source.read_bytes() != source_bytes:
            return _tool_failure("source changed during compilation; debug map invalidated")
    except OSError as exc:
        return _tool_failure(f"source unavailable after compilation; debug map invalidated: {exc}")
    save_variable_map(variables, identity=program_identity(source, st_code))
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
