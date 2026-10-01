"""Stable, public browser events from Codex CLI JSON events."""

from __future__ import annotations

from typing import Any


def _summary(item: dict[str, Any]) -> str:
    result = item.get("result")
    if isinstance(result, dict):
        structured = result.get("structuredContent") or result.get("structured_content") or result
        if isinstance(structured, dict):
            if item.get("tool") == "plc_find_symbol":
                return f"{structured.get('total', len(structured.get('matches') or []))} matches"
            if item.get("tool") == "plc_find_references":
                return f"{structured.get('total', len(structured.get('references') or []))} references"
            if item.get("tool") == "plc_check":
                diagnostics = structured.get("diagnostics") or []
                errors = sum(x.get("severity") == "error" for x in diagnostics if isinstance(x, dict))
                warnings = sum(x.get("severity") == "warning" for x in diagnostics if isinstance(x, dict))
                return f"{errors} errors, {warnings} warnings"
            if item.get("tool") == "plc_verify":
                return "passed" if structured.get("passed") is True else "failed"
            if "success" in structured:
                return "success" if structured["success"] else str((structured.get("error") or {}).get("message") or "failed")
    return str(item.get("status") or "completed")[:160]


class CodexEventAdapter:
    def __init__(self, turn_id: str = "") -> None:
        self._message_text: dict[str, str] = {}
        self._turn_id = turn_id

    def _id(self, item: dict[str, Any]) -> str:
        ident = str(item.get("id") or "message")
        return f"{self._turn_id}:{ident}" if self._turn_id else ident

    def convert(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        kind = event.get("type")
        item = event.get("item") or {}
        item_type = item.get("type")
        if kind == "thread.started":
            return [{"type": "thread.started", "thread_id": event.get("thread_id")}]
        if kind == "turn.started":
            return [{"type": "agent.status", "message": "Codex turn started"}]
        if item_type == "agent_message" and kind in {"item.started", "item.updated", "item.completed"}:
            ident = self._id(item)
            current = str(item.get("text") or "")
            prior = self._message_text.get(ident, "")
            delta = current[len(prior):] if current.startswith(prior) else current
            self._message_text[ident] = current
            return [{"type": "agent.message.delta", "id": ident, "text": delta}] if delta else []
        if item_type == "mcp_tool_call" and item.get("server") == "plc":
            if kind == "item.started":
                return [{"type": "tool.started", "id": self._id(item), "tool": item.get("tool")}]
            if kind == "item.completed":
                return [{"type": "tool.completed", "id": self._id(item), "tool": item.get("tool"),
                         "summary": _summary(item), "status": item.get("status", "completed")}]
        if item_type == "file_change" and kind == "item.completed":
            paths = []
            for change in item.get("changes") or []:
                if isinstance(change, dict) and isinstance(change.get("path"), str):
                    paths.append({"type": "file.changed", "path": change["path"], "source": "agent"})
            return paths
        if kind in {"turn.failed", "error"}:
            return [{"type": "agent.error", "message": str(event.get("message") or event.get("error") or "Codex turn failed")}]
        if kind == "turn.completed":
            return [{"type": "turn.completed"}]
        if kind == "infrastructure.stderr":
            # Codex can log a failed background model-list refresh while its
            # actual turn continues. Only the turn result decides failure.
            return []
        # Reasoning items, raw commands, and internal Codex JSON never cross the WebSocket.
        return []
