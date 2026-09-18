"""Stable M2 contracts for controlling the loaded OpenPLC program."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from runtime.openplc import OpenPLCConfigurationError, runtime_command, runtime_status


@dataclass(frozen=True)
class RuntimeResult:
    success: bool
    requested_status: str | None
    actual_status: str | None
    message: str
    tool_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def get_plc_status() -> RuntimeResult:
    try:
        status = runtime_status()
    except OpenPLCConfigurationError as exc:
        return RuntimeResult(False, None, None, "", str(exc))
    return RuntimeResult(True, None, status, f"PLC status is {status}")


def start_plc(*, timeout: float = 20.0) -> RuntimeResult:
    try:
        result = runtime_command("RUNNING", timeout=timeout)
    except OpenPLCConfigurationError as exc:
        return RuntimeResult(False, "RUNNING", None, "", str(exc))
    return RuntimeResult(
        result.actual_status == "RUNNING",
        "RUNNING",
        result.actual_status,
        result.message,
    )


def stop_plc(*, timeout: float = 20.0) -> RuntimeResult:
    try:
        result = runtime_command("STOPPED", timeout=timeout)
    except OpenPLCConfigurationError as exc:
        return RuntimeResult(False, "STOPPED", None, "", str(exc))
    return RuntimeResult(
        result.actual_status == "STOPPED",
        "STOPPED",
        result.actual_status,
        result.message,
    )
