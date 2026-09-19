"""Public M5 request/result contracts.

The contracts deliberately contain only JSON-compatible values.  They are used
by the CLI and by the agent adapter, while smolagents' internal memory remains
an implementation detail.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


FailureKind = Literal[
    "invalid_request",
    "model_unavailable",
    "model_output_invalid",
    "candidate_check_failed",
    "candidate_compile_failed",
    "runtime_start_failed",
    "behavior_verification_failed",
    "unverifiable_requirement",
    "attempt_limit_reached",
    "runtime_busy",
    "tool_unavailable",
]


@dataclass(frozen=True)
class M5Request:
    task: str
    max_attempts: int = 3
    source_filename: str = "candidate.st"

    def validate(self) -> str | None:
        if not isinstance(self.task, str) or not self.task.strip():
            return "task must be a non-empty string"
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            return "max_attempts must be an integer"
        if not 1 <= self.max_attempts <= 3:
            return "max_attempts must be between 1 and 3"
        if not isinstance(self.source_filename, str) or not self.source_filename.strip():
            return "source_filename must be a non-empty string"
        if not self.source_filename.lower().endswith(".st"):
            return "source_filename must end with .st"
        return None


@dataclass
class AttemptRecord:
    attempt: int
    st_code_digest: str
    phase: str
    check_result: dict[str, Any] | None = None
    compile_result: dict[str, Any] | None = None
    start_result: dict[str, Any] | None = None
    verify_result: dict[str, Any] | None = None
    stop_result: dict[str, Any] | None = None
    feedback: dict[str, Any] = field(default_factory=dict)
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class M5Result:
    success: bool
    failure_kind: FailureKind | None
    st_code: str | None
    verification_plan: dict[str, Any] | None
    attempts: list[AttemptRecord]
    final_message: str
    model: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attempts"] = [attempt.to_dict() for attempt in self.attempts]
        return payload

