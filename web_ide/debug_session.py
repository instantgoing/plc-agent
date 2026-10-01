"""One subscription union and one polling loop for all online IDE views."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict

from plc_tools.debug import TraceBuffer, program_state
from plc_tools.runtime import get_plc_status
from plc_tools.state import load_debug_state, load_variable_map
from plc_tools.variables import _SIZES


class DebugSession:
    def __init__(self, gateway):
        self.gateway = gateway
        self.interval_ms = 250
        self.subscriptions: dict[str, set[str]] = {}
        self.latest: dict[str, dict] = {}
        self.runtime = "offline"
        self.trace = TraceBuffer()
        self._lock = threading.RLock()
        self._last_status = 0.
        self._program_id = None
        self._catalog = []
        self._catalog_key = None
        self.poll_latency_ms = 0.
        self._runtime_consistency = None

    def catalog(self) -> list[dict]:
        entries = load_variable_map()
        program = program_state(self.gateway.workspace.root)
        key = (program["program_id"], program["consistency"])
        if key == self._catalog_key:
            return self._catalog
        # Source declarations and instance expansion are separate from live state.
        snapshot = self.gateway.plc.context_index.snapshot()
        pous = {p.name.casefold(): p for p in snapshot.pous}
        records = []
        def expand(owner, variables, stack=()):
            for v in variables:
                child = pous.get(v.type.casefold())
                if child and child.kind == "function_block" and child.name not in stack:
                    expand(f"{owner}.{v.name}", child.variables, (*stack, child.name))
                else:
                    records.append({"id": f"{owner}:{v.name}".casefold(), "name": v.name,
                                    "owner": owner, "scope": v.scope, "type": v.type.upper(),
                                    "address": v.address, "file": v.location.file, "line": v.location.line})
        for p in snapshot.pous:
            if p.kind == "program":
                expand(p.name, p.variables)
        expand("GVL", snapshot.globals)
        by_id = {v.id: v for v in entries if v.id}
        counts = {r["id"]: sum(x["id"] == r["id"] for x in records) for r in records}
        for record in records:
            match = by_id.get(record["id"]) if counts[record["id"]] == 1 else None
            record["available"] = bool(match and match.type in _SIZES and program["consistency"] == "matched")
            record["forceable"] = bool(record["available"] and match.location.startswith(("%I", "%Q")))
            record["address"] = match.location if match else record["address"]
        # Generated FB members (timer Q/ET, EN/ENO) do not exist as declarations.
        for entry in entries:
            if entry.id and entry.id not in counts and program["consistency"] == "matched":
                parent = next((r for r in records if entry.owner.casefold() == (r["owner"] + "." + r["name"]).casefold()), None)
                records.append({"id": entry.id, "name": entry.name.rsplit(".", 1)[-1], "owner": entry.owner,
                                "scope": entry.scope, "type": entry.type, "address": entry.location,
                                "available": entry.type in _SIZES, "forceable": entry.location.startswith(("%I", "%Q")),
                                "file": parent["file"] if parent else "", "line": parent["line"] if parent else 1})
        self._catalog_key, self._catalog = key, records
        return records

    def invalidate_source(self):
        with self._lock:
            self._catalog_key = None

    def subscribe(self, consumer: str, ids: list[str]):
        if not consumer or len(consumer) > 128 or len(ids) > 100 or not all(isinstance(i, str) for i in ids):
            raise ValueError("invalid subscription")
        with self._lock:
            if len(self.subscriptions) >= 32 and consumer not in self.subscriptions:
                raise ValueError("too many debug consumers")
            self.subscriptions[consumer] = set(ids)
        return self.snapshot()

    def unsubscribe(self, consumer: str):
        with self._lock:
            self.subscriptions.pop(consumer, None)

    def snapshot(self):
        with self._lock:
            now = int(time.time() * 1000)
            stale_ms = max(1500, self.interval_ms * 3)
            latest = {key: {**value, "state": "stale" if value["state"] in {"normal", "forced"} and value.get("last_updated") and
                       now - value["last_updated"] > stale_ms else value["state"]}
                      for key, value in self.latest.items()}
            return {"type": "debug.values", "timestamp": now, "runtime": self.runtime,
                    "interval_ms": self.interval_ms, "stale_after_ms": stale_ms,
                    "latest": latest, "values": {k: v["value"] for k, v in latest.items()
                       if v["state"] in {"normal", "forced"}},
                    "forced": load_debug_state().get("forced", {}), "force_scope": "tool-observed",
                    **program_state(self.gateway.workspace.root),
                    **({"consistency": self._runtime_consistency} if self._runtime_consistency else {}),
                    "trace": self.trace.metadata(),
                    "poll_latency_ms": self.poll_latency_ms}

    def configure(self, interval_ms: int):
        if interval_ms not in {100, 250, 500, 1000}:
            raise ValueError("interval must be 100, 250, 500 or 1000ms")
        self.interval_ms = interval_ms

    def start_trace(self, ids: list[str], interval_ms: int):
        with self._lock:
            catalog = {v["id"]: v for v in self.catalog()}
            state = self.snapshot()
            if state["runtime"] != "running" or state["consistency"] != "matched":
                raise ValueError("trace requires a running matching build")
            if any(i not in catalog or not catalog[i]["available"] for i in ids):
                raise ValueError("unresolved or unsupported trace signal")
            self.trace.start([{"variable_id": i, "type": catalog[i]["type"]} for i in ids], interval_ms, state["program_id"])
            return self.trace.metadata()

    def trace_action(self, action: str):
        with self._lock:
            if action == "stop":
                self.trace.stop()
            elif action == "clear":
                self.trace.stop()
                self.trace = TraceBuffer()
            elif action != "pause":
                raise ValueError("unknown trace action")
            else:
                self.trace.stop("paused")
            return self.trace.metadata()

    def poll(self):
        started = time.monotonic()
        with self._lock:
            state = program_state(self.gateway.workspace.root)
            if state["program_id"] != self._program_id:
                self.latest.clear()
                self.trace.stop("interrupted")
                self._program_id = state["program_id"]
                self._catalog_key = None
                self._runtime_consistency = None
            if started - self._last_status >= 1:
                status = get_plc_status()
                self.runtime = (status.actual_status or "offline").lower() if status.success else "offline"
                self._last_status = started
            ids = set().union(*self.subscriptions.values()) if self.subscriptions else set()
            if self.trace.state == "recording":
                ids.update(s["variable_id"] for s in self.trace.signals)
            catalog = {v["id"]: v for v in self.catalog()}
            targets = sorted(i for i in ids if i in catalog and catalog[i]["available"])
            result = {}
            if self.runtime == "running" and state["consistency"] == "matched" and targets:
                result = self.gateway.plc_call("read", targets)
                if result.get("runtime") != "running":
                    self.runtime = "offline"
            values = result.get("values", {})
            if result.get("consistency") == "runtime_mismatch":
                self._runtime_consistency = "runtime_mismatch"
            elif result.get("runtime") == "running":
                self._runtime_consistency = None
            timestamp = result.get("timestamp", int(time.time() * 1000))
            forced = result.get("forced", load_debug_state().get("forced", {}))
            self.latest = {i: {"value": values.get(i), "last_updated": timestamp if i in values else
                              self.latest.get(i, {}).get("last_updated"),
                              "state": ("forced" if i in forced else "normal") if i in values else
                                       "unresolved" if i not in catalog else "unavailable"} for i in ids}
            if self.runtime != "running" or state["consistency"] != "matched":
                self.trace.stop("interrupted")
            sample = self.trace.append(values, timestamp)
            self.poll_latency_ms = round((time.monotonic() - started) * 1000, 2)
            event = self.snapshot()
            if result.get("consistency") == "runtime_mismatch":
                event["consistency"] = "runtime_mismatch"
            if sample:
                event["trace_sample"] = sample
        self.gateway._publish(event)
        return event
