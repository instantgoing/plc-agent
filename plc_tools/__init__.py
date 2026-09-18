"""Stable PLC tool contracts exposed to the future Agent layer."""

from .check import CheckResult, Diagnostic, check_st, check_st_text
from .compile import CompileResult, compile_st
from .runtime import RuntimeResult, get_plc_status, start_plc, stop_plc
from .variables import (
    ForceVariablesResult,
    ReadVariablesResult,
    force_variables,
    read_variables,
)
from .verify import VerifyResult, verify_file, verify_plan

__all__ = [
    "CheckResult",
    "CompileResult",
    "Diagnostic",
    "RuntimeResult",
    "ForceVariablesResult",
    "ReadVariablesResult",
    "VerifyResult",
    "check_st",
    "check_st_text",
    "compile_st",
    "get_plc_status",
    "force_variables",
    "read_variables",
    "start_plc",
    "stop_plc",
    "verify_file",
    "verify_plan",
]
