"""Small, in-process experience counters for PLC sessions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .contracts import M5Result
from .events import PLCEvent


def _rate(successes: int, total: int) -> float | None:
    return round(successes / total, 3) if total else None


@dataclass
class SessionMetrics:
    turns: int = 0
    first_event_delays_ms: deque[int] = field(default_factory=lambda: deque(maxlen=100))
    clarification_questions: int = 0
    meaningless_tool_calls: int = 0
    schema_errors: int = 0
    runtime_attempts: int = 0
    repair_turns: int = 0
    repair_successes: int = 0
    continuation_turns: int = 0
    continuation_successes: int = 0
    cleanup_attempts: int = 0
    cleanup_successes: int = 0

    def record_event(self, event: PLCEvent) -> None:
        if event.name == "waiting_for_user":
            self.clarification_questions += 1
        elif event.name == "tool_call_rejected":
            if event.data.get("reason") != "tool_exception":
                self.meaningless_tool_calls += 1
            if event.data.get("reason") == "schema_error":
                self.schema_errors += 1
        elif event.name == "failed" and (
            event.data.get("phase") == "model_preflight"
            and event.data.get("failure_kind") == "model_output_invalid"
        ):
            self.schema_errors += 1
        elif event.name == "cleanup_completed":
            self.cleanup_attempts += 1
            stop = event.data.get("stop_result")
            release = event.data.get("release_result")
            if (
                isinstance(stop, dict) and stop.get("success") is True
                and (release is None or isinstance(release, dict) and release.get("success") is True)
            ):
                self.cleanup_successes += 1

    def record_turn(self, result: M5Result, *, resumed: bool, repaired: bool) -> None:
        self.turns += 1
        self.runtime_attempts += len(result.attempts)
        if repaired:
            self.repair_turns += 1
            if result.success:
                self.repair_successes += 1
        if resumed:
            self.continuation_turns += 1
            if result.success:
                self.continuation_successes += 1

    def to_dict(self) -> dict[str, Any]:
        delays = self.first_event_delays_ms
        return {
            "turns": self.turns,
            "first_progress_event_delay_ms": delays[-1] if delays else None,
            "average_first_progress_event_delay_ms": (
                round(sum(delays) / len(delays)) if delays else None
            ),
            "clarification_questions": self.clarification_questions,
            "meaningless_tool_calls": self.meaningless_tool_calls,
            "schema_errors": self.schema_errors,
            "runtime_attempts": self.runtime_attempts,
            "repair_turns": self.repair_turns,
            "repair_success_rate": _rate(self.repair_successes, self.repair_turns),
            "continuation_turns": self.continuation_turns,
            "continuation_success_rate": _rate(
                self.continuation_successes, self.continuation_turns
            ),
            "cleanup_attempts": self.cleanup_attempts,
            "cleanup_success_rate": _rate(self.cleanup_successes, self.cleanup_attempts),
        }
