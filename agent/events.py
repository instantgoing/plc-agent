"""UI-independent, in-process progress events for one PLC Agent turn."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal


EventName = Literal[
    "model_preflight_started",
    "model_preflight_passed",
    "tool_call_rejected",
    "requirement_analyzed",
    "waiting_for_user",
    "candidate_generated",
    "check_started",
    "check_failed",
    "compile_started",
    "runtime_started",
    "verification_step",
    "repair_started",
    "accepted",
    "failed",
    "cleanup_completed",
]


@dataclass(frozen=True)
class PLCEvent:
    name: EventName
    session_id: str | None
    turn: int
    sequence: int
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EventCallback = Callable[[PLCEvent], None]


class EventEmitter:
    """Never allow a presentation callback to interrupt PLC cleanup."""

    def __init__(
        self, callback: EventCallback | None = None, *, session_id: str | None = None, turn: int = 1
    ) -> None:
        self.callback = callback
        self.session_id = session_id
        self.turn = turn
        self.sequence = 0
        self.callback_errors: list[str] = []

    def emit(self, name: EventName, data: dict[str, Any] | None = None) -> None:
        if self.callback is None:
            return
        self.sequence += 1
        event = PLCEvent(name, self.session_id, self.turn, self.sequence, data or {})
        try:
            self.callback(event)
        except Exception as exc:
            self.callback_errors.append(f"{type(exc).__name__}: {exc}")
