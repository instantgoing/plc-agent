"""Stable M1 contract for real MatIEC compiler verification."""

from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from runtime.matiec import MatiecConfigurationError, run_iec2c


Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Diagnostic:
    message: str
    severity: Severity
    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    source_line: str = ""


@dataclass(frozen=True)
class CheckResult:
    success: bool
    errors: list[Diagnostic]
    warnings: list[Diagnostic]
    tool_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
            "tool_error": self.tool_error,
        }


# MatIEC v4 range form: file:line-col..line-col: severity: message
# Alternate builds use colons and a dash: file:line:col-line:col: ...
_RANGE_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+):(?P<line>\d+)[-:](?P<column>\d+)"
    r"(?:\.\.|-)(?P<end_line>\d+)[-:](?P<end_column>\d+):\s*"
    r"(?P<severity>error|warning):\s*(?P<message>.+)$",
    re.IGNORECASE,
)

_SIMPLE_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+):(?P<line>\d+)(?::(?P<column>\d+))?:\s*"
    r"(?P<severity>error|warning):\s*(?P<message>.+)$",
    re.IGNORECASE,
)


def _source_line(lines: list[str], line: int | None) -> str:
    if line is None or not 1 <= line <= len(lines):
        return ""
    return lines[line - 1].rstrip("\r")


def _parse_diagnostics(
    output: str, st_code: str, *, source_name: str | None = None
) -> list[Diagnostic]:
    source_lines = st_code.splitlines()
    diagnostics: list[Diagnostic] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = _RANGE_DIAGNOSTIC.match(line) or _SIMPLE_DIAGNOSTIC.match(line)
        if match is None:
            continue
        values = match.groupdict()
        line_number = int(values["line"])
        diagnostics.append(
            Diagnostic(
                message=values["message"].strip(),
                severity=cast(Severity, values["severity"].lower()),
                file=source_name or values["file"],
                line=line_number,
                column=int(values["column"]) if values.get("column") else None,
                end_line=int(values["end_line"]) if values.get("end_line") else None,
                end_column=int(values["end_column"]) if values.get("end_column") else None,
                source_line=_source_line(source_lines, line_number),
            )
        )
    return diagnostics


def _fallback_error(stderr: str, stdout: str) -> Diagnostic:
    raw = stderr.strip() or stdout.strip() or "MatIEC failed without diagnostic output"
    return Diagnostic(message=raw[:4000], severity="error")


def check_st(source_path: str | Path, *, timeout: float = 60.0) -> CheckResult:
    """Compile one real ST file with MatIEC and return structured diagnostics."""

    source = Path(source_path).resolve()
    if not source.is_file():
        return CheckResult(
            success=False,
            errors=[],
            warnings=[],
            tool_error=f"ST source does not exist: {source}",
        )

    try:
        st_code = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return CheckResult(False, [], [], f"cannot read ST source as UTF-8: {exc}")

    with tempfile.TemporaryDirectory(prefix="plc-agent-check-") as directory:
        try:
            completed = run_iec2c(source, Path(directory), timeout=timeout)
        except MatiecConfigurationError as exc:
            return CheckResult(False, [], [], str(exc))

    parsed = _parse_diagnostics(
        "\n".join(part for part in (completed.stderr, completed.stdout) if part),
        st_code,
        source_name=source.name,
    )
    errors = [item for item in parsed if item.severity == "error"]
    warnings = [item for item in parsed if item.severity == "warning"]
    if completed.returncode != 0 and not errors:
        errors.append(_fallback_error(completed.stderr, completed.stdout))
    return CheckResult(completed.returncode == 0, errors, warnings)


def check_st_text(
    st_code: str, *, filename: str = "program.st", timeout: float = 60.0
) -> CheckResult:
    """Check ST held in memory without changing the public result contract."""

    safe_name = Path(filename).name
    if not safe_name.lower().endswith(".st"):
        safe_name += ".st"
    with tempfile.TemporaryDirectory(prefix="plc-agent-source-") as directory:
        source = Path(directory) / safe_name
        source.write_text(st_code, encoding="utf-8")
        return check_st(source, timeout=timeout)
