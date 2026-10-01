"""Stable M2 contracts for controlling the loaded OpenPLC program."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from runtime.openplc import OpenPLCConfigurationError, runtime_command, runtime_status
from plc_tools.state import serialized_debug, load_debug_state


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


@serialized_debug
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


@serialized_debug
def stop_plc(*, timeout: float = 20.0) -> RuntimeResult:
    known = list(load_debug_state().get("forced", {}))
    cleanup_error = None
    if known:
        from plc_tools.variables import _force_variables
        released = _force_variables({}, release=known, timeout=min(timeout, 5.0))
        if not released.success:
            cleanup_error = released.tool_error or "; ".join(f.reason for f in released.failures)
    try:
        result = runtime_command("STOPPED", timeout=timeout)
    except OpenPLCConfigurationError as exc:
        return RuntimeResult(False, "STOPPED", None, "", str(exc))
    return RuntimeResult(
        result.actual_status == "STOPPED" and cleanup_error is None,
        "STOPPED",
        result.actual_status,
        result.message,
        f"Force cleanup failed: {cleanup_error}" if cleanup_error else None,
    )
