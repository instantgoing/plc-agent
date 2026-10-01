"""Runtime observations and bounded traces shared by MCP, CLI and the IDE."""
from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from plc_tools.state import load_debug_state, load_variable_map
from plc_tools.variables import _resolve, read_variables


def program_state(root: Path) -> dict:
    program = load_debug_state().get("program")
    consistency = "unknown"
    if program:
        source = Path(program["source_file"])
        if source.resolve().is_relative_to(root.resolve()):
            try:
                digest = hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest()
                consistency = "matched" if digest == program["source_hash"] else "mismatch"
            except (OSError, UnicodeError):
                consistency = "mismatch"
    return {"program": program, "program_id": program.get("build_id") if program else None,
            "consistency": consistency}


def debug_snapshot(variables: list[str], root: Path) -> dict:
    before_program = load_debug_state().get("program")
    entries = load_variable_map()
    resolved, missing = _resolve(variables, entries)
    result = read_variables(variables)
    by_index = {v.index: v for v in result.variables.values()}
    values = {name: by_index[v.index].value for name in variables
              for v in resolved if v.index in by_index
              and (name.casefold() in {v.id.casefold(), v.name.casefold(), v.runtime_path.casefold()})
              and name not in missing}
    state = load_debug_state()
    if state.get("program") != before_program:
        return {"success": False, "values": {}, "timestamp": int(time.time() * 1000),
                "runtime": "unavailable", "forced": state.get("forced", {}), **program_state(root),
                "error": {"type": "program_changed", "message": "program changed during snapshot"}}
    return {"success": result.success and not result.unresolved_names, "values": values,
            "variables": {name: vars(item) for name, item in result.variables.items()},
            "timestamp": int(time.time() * 1000), "scan": result.tick,
            "runtime": "running" if result.success and result.tick is not None else "unavailable",
            "forced": state.get("forced", {}), "force_scope": "tool-observed",
            "unresolved": result.unresolved_names, **program_state(root),
            **({"consistency": "runtime_mismatch"} if result.tool_error and "program hash differs" in result.tool_error else {}),
            **({"error": {"type": "read_failed", "message": result.tool_error}} if result.tool_error else
               {"error": {"type": "unknown_variable", "message": "unresolved or unsupported variable",
                          "variable": result.unresolved_names[0]}} if result.unresolved_names else {})}


class TraceBuffer:
    def __init__(self, max_samples: int = 10000):
        if not 1 <= max_samples <= 10000:
            raise ValueError("trace capacity must be between 1 and 10000")
        self.samples: deque = deque(maxlen=max_samples)
        self.signals: list[dict] = []
        self.session_id: str | None = None
        self.state = "idle"
        self.started_at: str | None = None
        self.interval_ms = 100
        self.program_id = None
        self.dropped = 0
        self._origin = 0.
        self._last = -float("inf")

    def start(self, signals: list[dict], interval_ms: int, program_id: str | None):
        if not signals or len(signals) > 100 or interval_ms not in {100, 250, 500, 1000}:
            raise ValueError("choose 1-100 signals and a supported interval")
        if self.state == "recording":
            raise ValueError("trace already recording")
        self.samples.clear()
        self.signals = list({s["variable_id"]: s for s in signals}.values())
        self.session_id = uuid.uuid4().hex
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.interval_ms = interval_ms
        self.program_id = program_id
        self.dropped = 0
        self._origin = time.monotonic()
        self._last = -float("inf")
        self.state = "recording"

    def append(self, values: dict, timestamp: int, *, monotonic: float | None = None):
        now = time.monotonic() if monotonic is None else monotonic
        if self.state != "recording" or (now - self._last) * 1000 < self.interval_ms - 1:
            return None
        ids = [s["variable_id"] for s in self.signals]
        if any(key not in values for key in ids):
            self.stop("interrupted")
            return None
        sample = {"t_ms": round((now - self._origin) * 1000), "timestamp": timestamp,
                  "values": {key: values[key] for key in ids}}
        if len(self.samples) == self.samples.maxlen:
            self.dropped += 1
        self.samples.append(sample)
        self._last = now
        return sample

    def stop(self, state: str = "stopped"):
        if self.state == "recording":
            self.state = state

    def metadata(self) -> dict:
        return {"session_id": self.session_id, "started_at": self.started_at,
                "sample_interval_ms": self.interval_ms, "signals": self.signals,
                "state": self.state, "program_id": self.program_id,
                "sample_count": len(self.samples), "capacity": self.samples.maxlen,
                "dropped_samples": self.dropped}

    def data(self, start_ms: int = 0, end_ms: int | None = None) -> dict:
        return {**self.metadata(), "samples": [s for s in self.samples
                 if s["t_ms"] >= start_ms and (end_ms is None or s["t_ms"] <= end_ms)]}

    def summary(self) -> dict:
        return {**self.metadata(), "summary": summarize_trace(self.signals, list(self.samples))}


def summarize_trace(signals: list[dict], samples: list[dict]) -> dict:
    summary = {}
    for signal in signals:
        key = signal["variable_id"]
        points = [(s["t_ms"], s["values"][key]) for s in samples if key in s["values"]]
        if not points:
            summary[key] = {"samples": 0}
        elif signal["type"].upper() == "BOOL":
            edges = [{"t_ms": t, "value": v} for i, (t, v) in enumerate(points)
                     if i == 0 or v != points[i - 1][1]]
            summary[key] = {"transitions": edges[:200], "transition_count": len(edges),
                            "truncated": len(edges) > 200, "start": points[0][1], "end": points[-1][1]}
        else:
            values = [v for _, v in points if isinstance(v, (int, float)) and not isinstance(v, bool)]
            summary[key] = {"min": min(values) if values else None, "max": max(values) if values else None,
                            "start": points[0][1], "end": points[-1][1], "samples": len(points)}
    return summary
