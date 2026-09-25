"""Bounded, in-process PLC conversation state; no persistence or UI dependency."""

from __future__ import annotations

import json
import time
from collections import deque
from threading import Event, Lock
from typing import Any
from uuid import uuid4

from .contracts import M5Request, M5Result, RequirementSpec
from .events import EventCallback, PLCEvent
from .metrics import SessionMetrics
from .plc_agent import PLCRepairAgent


class PLCSession:
    """Carry only controlled state across turns, never full model chat history."""

    def __init__(
        self,
        *,
        agent: PLCRepairAgent | None = None,
        session_id: str | None = None,
        on_event: EventCallback | None = None,
        max_actions: int = 8,
        max_runtime_attempts: int = 3,
    ) -> None:
        self.session_id = session_id or str(uuid4())
        self.agent = agent or PLCRepairAgent()
        self.on_event = on_event
        self.max_actions = max_actions
        self.max_runtime_attempts = max_runtime_attempts
        self.requirement_spec: RequirementSpec | None = None
        self.current_st: str | None = None
        self.current_plan: dict[str, Any] | None = None
        self.last_verification_result: dict[str, Any] | None = None
        self.confirmed_assumptions: list[str] = []
        self.turn_summaries: deque[dict[str, Any]] = deque(maxlen=6)
        self.recent_events: deque[PLCEvent] = deque(maxlen=100)
        self.event_callback_errors: deque[str] = deque(maxlen=20)
        self.last_result: M5Result | None = None
        self.metrics = SessionMetrics()
        self.turn = 0
        self._lock = Lock()
        self._active_cancel: Event | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active_cancel is not None

    def confirm_assumptions(self, assumptions: list[str]) -> None:
        """Record only assumptions explicitly confirmed by the caller/user."""

        if not isinstance(assumptions, list) or any(
            not isinstance(item, str) or not item.strip() for item in assumptions
        ):
            raise ValueError("assumptions must be a list of non-empty strings")
        with self._lock:
            for item in assumptions:
                if item not in self.confirmed_assumptions:
                    self.confirmed_assumptions.append(item)
            self.confirmed_assumptions = self.confirmed_assumptions[-16:]

    def submit(
        self, user_message: str, *, on_event: EventCallback | None = None
    ) -> M5Result:
        if self.turn:
            raise ValueError("session already has a turn; use resume")
        return self._run_turn(user_message, resume=False, on_event=on_event)

    def resume(
        self, user_message: str, *, on_event: EventCallback | None = None
    ) -> M5Result:
        if not self.turn:
            raise ValueError("session has no prior turn; use submit")
        return self._run_turn(user_message, resume=True, on_event=on_event)

    def cancel(self) -> bool:
        """Request cooperative cancellation of the active turn; do not touch idle Runtime."""

        with self._lock:
            if self._active_cancel is None:
                return False
            self._active_cancel.set()
            return True

    def metrics_dict(self) -> dict[str, Any]:
        with self._lock:
            return self.metrics.to_dict()

    def _context(self, user_message: str) -> str:
        context: dict[str, Any] = {
            "previous_requirement_spec": (
                self.requirement_spec.to_dict() if self.requirement_spec else None
            ),
            "user_confirmed_assumptions": self.confirmed_assumptions,
            "recent_turn_summaries": list(self.turn_summaries),
        }
        if self.current_st is not None:
            context["last_verified_st"] = self.current_st
            context["last_verified_plan"] = self.current_plan
            context["instruction"] = (
                "Use the verified program as the starting point. Apply only the user's "
                "requested change, then preflight and behavior-verify the complete result. "
                "Do not assume the old verification proves the new program."
            )
        if self.last_verification_result is not None:
            context["recent_runtime_evidence"] = {
                "passed": self.last_verification_result.get("passed"),
                "failures": self.last_verification_result.get("failures", [])[:8],
                "steps": self.last_verification_result.get("steps", [])[:8],
            }
        return (
            "Latest user message (highest priority for this turn):\n"
            f"{user_message}\n\n"
            "Controlled context from this same PLC session (not a new user request):\n"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
            + "\nRe-submit an updated RequirementSpec before generating code. If the user "
            "corrected an earlier assumption, the correction wins."
        )

    def _run_turn(
        self, user_message: str, *, resume: bool, on_event: EventCallback | None
    ) -> M5Result:
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("user_message must be a non-empty string")
        with self._lock:
            if self._active_cancel is not None:
                raise RuntimeError("a session turn is already running")
            cancel_event = Event()
            self._active_cancel = cancel_event
            self.turn += 1
            turn = self.turn
            prompt = self._context(user_message) if resume else user_message
        started_at = time.monotonic()
        first_event = False
        had_repair = False

        def emit(event: PLCEvent) -> None:
            nonlocal first_event, had_repair
            with self._lock:
                self.recent_events.append(event)
                if not first_event:
                    self.metrics.first_event_delays_ms.append(
                        round((time.monotonic() - started_at) * 1000)
                    )
                    first_event = True
                if event.name == "repair_started":
                    had_repair = True
                self.metrics.record_event(event)
            for callback in (self.on_event, on_event):
                if callback is not None:
                    try:
                        callback(event)
                    except Exception as exc:
                        # The UI observer must never interrupt force release or Runtime stop.
                        with self._lock:
                            self.event_callback_errors.append(
                                f"{type(exc).__name__}: {exc}"
                            )

        try:
            result = self.agent.run(
                M5Request(
                    task=prompt,
                    max_attempts=self.max_runtime_attempts,
                    max_actions=self.max_actions,
                ),
                on_event=emit,
                cancel_event=cancel_event,
                session_id=self.session_id,
                turn=turn,
            )
            with self._lock:
                self.last_result = result
                self.metrics.record_turn(result, resumed=resume, repaired=had_repair)
                if result.requirement_spec is not None:
                    self.requirement_spec = RequirementSpec(**result.requirement_spec)
                    # A corrected requirement must not carry forward an old
                    # confirmation that the updated spec no longer contains.
                    self.confirmed_assumptions = [
                        item for item in self.confirmed_assumptions
                        if item in self.requirement_spec.assumptions
                    ]
                if result.success:
                    self.current_st = result.st_code
                    self.current_plan = result.verification_plan
                if result.attempts and result.attempts[-1].verify_result is not None:
                    self.last_verification_result = result.attempts[-1].verify_result
                self.turn_summaries.append(
                    {
                        "turn": turn,
                        "user_message": user_message[:300],
                        "state": result.state,
                        "runtime_attempts": len(result.attempts),
                        "outcome": result.final_message[:300],
                    }
                )
            return result
        finally:
            with self._lock:
                self._active_cancel = None


__all__ = ["PLCSession"]
