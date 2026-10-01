"""Long-lived local gateway state; browser disconnects do not stop Codex."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.codex_client import CodexClient, CodexInfrastructureError, _codex_binary, _codex_environment
from agent.codex_session import CodexPLCSession
from plc_tools.mcp_adapter import PLCMCPAdapter
from web_ide.events import CodexEventAdapter
from web_ide.workspace import Workspace
from web_ide.connectivity import ensure_local_proxy
from web_ide.debug_session import DebugSession


class Gateway:
    def __init__(self, root: str | Path):
        self.workspace = Workspace(root)
        self.plc = PLCMCPAdapter(self.workspace.root)
        self.environment = "simulation"
        self._plc_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._session: CodexPLCSession | None = None
        self._session_lock = threading.Lock()
        self._agent_lock = threading.Lock()
        self._active = False
        self._worker: threading.Thread | None = None
        self._event_id = 0
        self._event_lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=1000)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_snapshot = self.workspace.snapshot()
        self._before: dict[str, str] = {}
        self._changes: dict[str, dict[str, Any]] = {}
        self._meta_file = self.workspace.root / ".plc-agent" / "web-sessions.json"
        self._sessions = self._load_sessions()
        self.debug = DebugSession(self)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _load_sessions(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._meta_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_sessions(self) -> None:
        self._meta_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._meta_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self._meta_file)

    def session(self) -> CodexPLCSession:
        with self._session_lock:
            if self._session is None:
                self._session = CodexPLCSession(workspace=self.workspace.root)
            return self._session

    def sessions(self) -> dict:
        active = None
        try:
            active = self.session().thread_id
        except CodexInfrastructureError:
            pass
        return {"current_thread_id": active, "active": self._active,
                "sessions": list(reversed(self._sessions))}

    def new_session(self) -> dict:
        if self._active:
            raise RuntimeError("agent turn is active")
        session = self.session()
        session.thread_id = None
        session._save()
        with self._event_lock:
            self._events.clear()
        return self.sessions()

    def resume_session(self, thread_id: str) -> dict:
        if self._active:
            raise RuntimeError("agent turn is active")
        if not any(item.get("thread_id") == thread_id for item in self._sessions):
            raise ValueError("unknown thread ID")
        session = self.session()
        session.thread_id = thread_id
        session._save()
        with self._event_lock:
            self._events.clear()
        return self.sessions()

    def _record_thread(self, thread_id: str, title: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        item = next((row for row in self._sessions if row.get("thread_id") == thread_id), None)
        if item is None:
            self._sessions.append({"thread_id": thread_id, "workspace": str(self.workspace.root),
                                   "created_at": now, "updated_at": now, "title": title[:80]})
        else:
            item["updated_at"] = now
        self._save_sessions()

    def _publish(self, event: dict[str, Any]) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        def deliver() -> None:
            payload = event
            # Live observations must never replay old green highlights after reconnect.
            if not event["type"].startswith("debug."):
                with self._event_lock:
                    self._event_id += 1
                    payload = {"seq": self._event_id, **event}
                    self._events.append(payload)
            for queue in tuple(self._subscribers):
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    self._subscribers.discard(queue)
        try:
            self._loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            pass

    def subscribe(self, after: int) -> tuple[asyncio.Queue, list[dict[str, Any]], bool]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=300)
        history, gap = self.event_history(after)
        self._subscribers.add(queue)
        return queue, history, gap

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def events(self, after: int) -> list[dict[str, Any]]:
        return self.event_history(after)[0]

    def event_history(self, after: int) -> tuple[list[dict[str, Any]], bool]:
        with self._event_lock:
            history = [event for event in self._events if event["seq"] > after]
            gap = bool(self._events and after < self._events[0]["seq"] - 1)
            return history, gap

    def scan_changes(self, source: str = "external") -> None:
        with self._snapshot_lock:
            now = self.workspace.snapshot()
            for path in sorted(self._last_snapshot.keys() | now.keys()):
                if self._last_snapshot.get(path) == now.get(path):
                    continue
                original = self._before.get(path, self._last_snapshot.get(path, ""))
                self._changes[path] = {"path": path, "source": source, "before": original,
                                       "after": now.get(path, "")}
                self._publish({"type": "file.changed", "path": path, "source": source})
            self._last_snapshot = now
        self.debug.invalidate_source()

    def changes(self) -> list[dict]:
        with self._snapshot_lock:
            return [{"path": row["path"], "source": row["source"]}
                    for row in sorted(self._changes.values(), key=lambda row: row["path"])]

    def diff(self, path: str) -> dict:
        self.workspace.path(path)
        with self._snapshot_lock:
            if path not in self._changes:
                raise KeyError(path)
            return self._changes[path]

    def run_agent(self, message: str) -> None:
        with self._agent_lock:
            if self._active:
                raise RuntimeError("agent turn is active")
            self._active = True
        self._before = self.workspace.snapshot()
        adapter = CodexEventAdapter(uuid.uuid4().hex)
        self._publish({"type": "agent.status", "message": "Connecting to Codex"})

        def work() -> None:
            try:
                self._publish({"type": "agent.status", "message": ensure_local_proxy()})
                session = self.session()
                def on_event(raw: dict[str, Any]) -> None:
                    for event in adapter.convert(raw):
                        # Snapshot detection publishes one canonical workspace-relative event.
                        if event["type"] != "file.changed":
                            self._publish(event)
                    if raw.get("type") == "item.completed":
                        self.scan_changes("agent")
                debug = self.debug.snapshot()
                trace = self.debug.trace.summary()
                observations = {"runtime": debug["runtime"], "program_id": debug["program_id"],
                                "consistency": debug["consistency"], "timestamp": debug["timestamp"],
                                "latest": debug["latest"], "forced": debug["forced"], "trace": trace}
                context = json.dumps(observations, ensure_ascii=False)
                result = session.run(message + "\nIDE runtime observations (refresh with plc_read before relying on them):\n" + context, on_event=on_event)
                if result.thread_id:
                    self._record_thread(result.thread_id, message)
                self.scan_changes("agent")
                public = {key: value for key, value in result.to_dict().items()
                          if key in {"success", "state", "final_message", "thread_id", "files_modified", "last_failure", "diagnostics"}}
                if public.get("state") == "agent_infrastructure_error":
                    self._publish({"type": "agent.error", "message": public.get("last_failure") or public.get("final_message")})
                self._publish({"type": "agent.result", "result": public})
            except Exception as exc:
                self._publish({"type": "agent.error", "message": str(exc)})
            finally:
                self._active = False
                self._publish({"type": "agent.idle"})

        self._worker = threading.Thread(target=work, daemon=True, name="web-ide-codex")
        self._worker.start()

    def interrupt(self) -> bool:
        return self.session().interrupt() if self._active else False

    def shutdown(self) -> None:
        if self._active:
            self.interrupt()
        if self._worker is not None:
            self._worker.join(timeout=10)

    def plc_call(self, method: str, *args: Any, **kwargs: Any) -> dict:
        with self._plc_lock:
            return getattr(self.plc, method)(*args, **kwargs)

    def codex_status(self) -> str:
        try:
            client = CodexClient(executable=_codex_binary())
            client._check_auth()
        except CodexInfrastructureError:
            return "authentication_error"
        proxy = _codex_environment().get("HTTPS_PROXY")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy} if proxy else {}))
        request = urllib.request.Request("https://api.openai.com/v1/models", method="HEAD")
        try:
            with opener.open(request, timeout=6):
                pass
        except urllib.error.HTTPError:
            # A 401 without a probe credential still proves the HTTPS path works.
            return "ready"
        except (urllib.error.URLError, TimeoutError, OSError):
            return "network_unavailable"
        return "ready"
