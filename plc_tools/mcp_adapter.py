"""MCP-facing, JSON-serializable views of the existing PLC tool contracts."""

from __future__ import annotations

import time
import os
import json
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from plc_context import ProjectIndexer
from plc_tools.debug import debug_snapshot, program_state, TraceBuffer
from plc_tools.state import load_debug_state, load_variable_map
from plc_tools.variables import _resolve, _SIZES, unforce_variables
from plc_tools import (
    check_st, compile_st, force_variables, read_variables, start_plc, stop_plc,
    verify_file,
)


def _error(kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {"type": kind, "message": message, **details}


class PLCMCPAdapter:
    """Keep path policy and response normalization out of the PLC core."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("project_root must be a directory")
        self.context_index = ProjectIndexer(self.root)
        self.context_index.snapshot()
        self.trace_buffer = TraceBuffer()

    def _file(self, file: str, *, suffix: str) -> tuple[Path | None, dict[str, Any] | None]:
        if not isinstance(file, str) or not file.strip() or "\x00" in file:
            return None, _error("invalid_argument", "file must be a nonempty path")
        path = (self.root / file).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() != suffix:
            return None, _error("invalid_argument", f"file must be a {suffix} inside the project")
        if not path.is_file():
            return None, _error("file_not_found", f"file does not exist: {file}")
        return path, None

    def project_info(self) -> dict[str, Any]:
        excluded = {".git", ".plc-agent", ".venv", "smolagents", "__pycache__"}
        files = sorted(
            path.relative_to(self.root).as_posix() for path in self.root.rglob("*.st")
            if not any(part in excluded for part in path.relative_to(self.root).parts)
        )
        return {
            "success": True, "project_root": str(self.root), "source_files": files,
            "runtime": "openplc", "compiler": "matiec",
            "capabilities": {"check": True, "compile": True, "run": True,
                             "force": True, "unforce": True, "read": True, "trace": True, "verify": True},
            "safety_levels": {"project_info": 0, "check": 0, "read": 0,
                              "compile": 1, "trace": 1, "start": 2, "stop": 2,
                              "force": 2, "unforce": 2, "verify": 2, "real_plc": 3},
        }

    def project_context(self, detail: str = "summary", limit: int = 100,
                        offset: int = 0) -> dict[str, Any]:
        if not isinstance(detail, str) or not isinstance(limit, int) or not 1 <= limit <= 500 or not isinstance(offset, int) or offset < 0:
            return {"success": False, "error": _error("invalid_argument", "detail, limit, or offset is invalid")}
        return self.context_index.project_context(detail, limit=limit, offset=offset)

    def find_symbol(self, query: str, match: str = "exact", limit: int = 100) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or not isinstance(match, str) or not isinstance(limit, int) or not 1 <= limit <= 500:
            return {"success": False, "matches": [], "error": _error("invalid_argument", "query, match, or limit is invalid")}
        return self.context_index.find_symbol(query.strip(), match=match, limit=limit)

    def find_references(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        if not isinstance(symbol, str) or not symbol.strip() or not isinstance(limit, int) or not 1 <= limit <= 500:
            return {"success": False, "references": [], "error": _error("invalid_argument", "symbol or limit is invalid")}
        return self.context_index.find_references(symbol.strip(), limit=limit)

    def check(self, file: str) -> dict[str, Any]:
        path, error = self._file(file, suffix=".st")
        if error:
            return {"success": False, "diagnostics": [], "error": error}
        assert path is not None
        result = check_st(path)
        diagnostics = [
            {**asdict(item), "file": file, "code": None}
            for item in (*result.errors, *result.warnings)
        ]
        payload = {"success": result.success, "diagnostics": diagnostics}
        if result.tool_error:
            payload["error"] = _error("infrastructure_error", result.tool_error)
        return payload

    def compile(self, file: str) -> dict[str, Any]:
        path, error = self._file(file, suffix=".st")
        if error:
            return {"success": False, "artifact": None, "diagnostics": [], "error": error}
        assert path is not None
        started = time.monotonic()
        result = compile_st(path)
        payload: dict[str, Any] = {
            "success": result.success, "artifact": None,
            "diagnostics": [{**asdict(item), "file": file, "code": None}
                            for item in (*result.errors, *result.warnings)],
            "duration_ms": round((time.monotonic() - started) * 1000),
            "failed_stage": result.failed_stage,
            "runtime_compile_status": result.runtime_compile_status,
            "runtime_logs": result.runtime_logs,
            "generated_files": result.generated_files,
            "variables": [asdict(item) for item in result.variables],
            **program_state(self.root),
        }
        if not result.success:
            kind = "infrastructure_error" if result.tool_error else "compiler_error"
            detail = result.tool_error or "; ".join(item.message for item in result.errors)
            if not detail:
                detail = "compilation failed at " + str(result.failed_stage)
            payload["error"] = _error(kind, detail)
        return payload

    def _runtime(self, operation: str) -> dict[str, Any]:
        result = start_plc() if operation == "start" else stop_plc()
        state = (result.actual_status or "error").lower() if result.success else "error"
        payload: dict[str, Any] = {"success": result.success, "state": state}
        if not result.success:
            if result.actual_status:
                payload["actual_status"] = result.actual_status.lower()
            payload["error"] = _error(
                "runtime_start_failed" if operation == "start" else "infrastructure_error",
                result.tool_error or result.message or f"runtime {operation} failed",
            )
        return payload

    def start(self) -> dict[str, Any]:
        return self._runtime("start")

    def stop(self) -> dict[str, Any]:
        return self._runtime("stop")

    def force(self, variables: dict[str, bool | int | float | str],
              release: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(variables, dict) or not isinstance(release or [], list):
            return {"success": False, "applied": {}, "error": _error("invalid_argument", "variables must be an object and release must be a list")}
        if not variables and not release:
            return {"success": False, "applied": {}, "error": _error("invalid_argument", "provide variables or release names")}
        result = force_variables(variables, release=release)
        payload: dict[str, Any] = {"success": result.success, "applied": result.forced,
                                   "released": result.released,
                                   "failures": [asdict(item) for item in result.failures]}
        if not result.success:
            unknown = next((item for item in result.failures if item.reason == "variable not found"), None)
            if unknown:
                payload["error"] = _error("unknown_variable", unknown.reason, variable=unknown.name)
            else:
                detail = result.tool_error or "; ".join(item.reason for item in result.failures)
                kind = "runtime_not_running" if "not running" in detail.lower() else "force_failed"
                payload["error"] = _error(kind, detail)
        return payload

    def read(self, variables: list[str]) -> dict[str, Any]:
        if not isinstance(variables, list) or not variables or not all(isinstance(x, str) and x for x in variables):
            return {"success": False, "values": {}, "error": _error("invalid_argument", "variables must be a nonempty list of names")}
        return debug_snapshot(variables, self.root)

    def unforce(self, variables: list[str]) -> dict:
        if not isinstance(variables, list) or not variables or not all(isinstance(v, str) for v in variables):
            return {"success": False, "error": _error("invalid_argument", "provide variable IDs")}
        return unforce_variables(variables).to_dict()

    def trace(self, variables: list[str] | None = None, duration_ms: int = 1000,
              sample_interval_ms: int = 100, action: str = "record",
              start_ms: int = 0, end_ms: int | None = None) -> dict:
        trace_url = os.environ.get("PLC_DEBUG_GATEWAY_URL")
        if action in {"summary", "range"} and trace_url and self.trace_buffer.session_id is None:
            parsed = urllib.parse.urlparse(trace_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password:
                return {"success": False, "error": _error("invalid_argument", "debug gateway must be local")}
            query = {"summary": "true"} if action == "summary" else {"start_ms": start_ms}
            if end_ms is not None and action == "range":
                query["end_ms"] = end_ms
            try:
                with urllib.request.urlopen(trace_url.rstrip("/") + "/api/debug/trace?" + urllib.parse.urlencode(query), timeout=3) as response:
                    selected = json.load(response)
                if Path(selected.get("workspace", "")).resolve() != self.root:
                    raise ValueError("trace belongs to another workspace")
                return {"success": True, **selected}
            except (OSError, ValueError) as exc:
                return {"success": False, "error": _error("trace_unavailable", str(exc))}
        if action == "summary":
            return {"success": True, **self.trace_buffer.summary()}
        if action == "range":
            return {"success": True, **self.trace_buffer.data(start_ms, end_ms)}
        if action != "record" or not 100 <= duration_ms <= 30000:
            return {"success": False, "error": _error("invalid_argument", "record duration must be 100-30000ms")}
        targets, missing = _resolve(variables or [], load_variable_map())
        if missing or not targets or any(v.type not in _SIZES for v in targets):
            return {"success": False, "error": _error("unknown_variable", "trace requires resolved supported signals")}
        try:
            self.trace_buffer.start([{"variable_id": v.id or v.name, "type": v.type} for v in targets],
                                    sample_interval_ms, program_state(self.root)["program_id"])
        except ValueError as exc:
            return {"success": False, "error": _error("invalid_argument", str(exc))}
        deadline = time.monotonic() + duration_ms / 1000
        while time.monotonic() < deadline:
            result = self.read([s["variable_id"] for s in self.trace_buffer.signals])
            if not result.get("success") or result["program_id"] != self.trace_buffer.program_id:
                self.trace_buffer.stop("interrupted")
                return {"success": False, **self.trace_buffer.summary(), "error": result.get("error")}
            self.trace_buffer.append(result["values"], result["timestamp"])
            time.sleep(sample_interval_ms / 1000)
        self.trace_buffer.stop()
        return {"success": True, **self.trace_buffer.summary()}

    def verify(self, file: str) -> dict[str, Any]:
        path, error = self._file(file, suffix=".json")
        if error:
            return {"success": False, "passed": False, "results": [], "error": error}
        assert path is not None
        result = verify_file(path)
        execution_failures = [item for item in result.failures
                              if item.reason.startswith("force failed:")
                              or item.reason.startswith("read failed:")
                              or item.reason == "forced-variable release failed"]
        executed = result.tool_error is None and not result.cancelled and not execution_failures
        payload: dict[str, Any] = {"success": executed,
                                   "passed": result.passed,
                                   "results": [asdict(item) for item in result.steps],
                                   "failures": [asdict(item) for item in result.failures],
                                   "cleanup_result": result.cleanup_result}
        if result.tool_error:
            kind = ("runtime_not_running" if "RUNNING" in result.tool_error else
                    "invalid_argument" if result.tool_error.startswith(("test plan", "step ", "cannot read test plan")) else
                    "verification_failed")
            payload["error"] = _error(kind, result.tool_error)
        elif execution_failures:
            payload["error"] = _error("verification_failed", execution_failures[0].reason)
        return payload
