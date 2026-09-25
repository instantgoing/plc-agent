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
    "candidate_not_validated",
    "candidate_compile_failed",
    "runtime_start_failed",
    "behavior_verification_failed",
    "unverifiable_requirement",
    "attempt_limit_reached",
    "runtime_busy",
    "tool_unavailable",
    "model_authentication_failed",
    "model_connection_failed",
    "model_tool_unsupported",
    "model_context_exceeded",
    "agent_reported_failure",
    "action_limit_reached",
    "cancelled",
]

RunState = Literal[
    "understanding",
    "needs_user_input",
    "requirement_ready",
    "candidate_ready",
    "validating",
    "candidate_validated",
    "evaluating",
    "repairable_failure",
    "accepted",
    "unverifiable",
    "fatal_failure",
    "exhausted",
    "cancelled",
]

TERMINAL_RUN_STATES: frozenset[RunState] = frozenset(
    {
        "needs_user_input",
        "accepted",
        "unverifiable",
        "fatal_failure",
        "exhausted",
        "cancelled",
    }
)

_RUN_STATE_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    "understanding": frozenset(
        {"needs_user_input", "requirement_ready", "unverifiable", "fatal_failure", "exhausted", "cancelled"}
    ),
    "needs_user_input": frozenset(),
    "requirement_ready": frozenset(
        {"needs_user_input", "candidate_ready", "unverifiable", "fatal_failure", "exhausted", "cancelled"}
    ),
    "candidate_ready": frozenset({"validating", "cancelled"}),
    "validating": frozenset(
        {"candidate_validated", "repairable_failure", "fatal_failure", "exhausted", "cancelled"}
    ),
    "candidate_validated": frozenset(
        {
            "needs_user_input",
            "candidate_ready",
            "evaluating",
            "unverifiable",
            "fatal_failure",
            "exhausted",
            "cancelled",
        }
    ),
    "evaluating": frozenset(
        {"repairable_failure", "accepted", "fatal_failure", "exhausted", "cancelled"}
    ),
    "repairable_failure": frozenset(
        {
            "needs_user_input",
            "requirement_ready",
            "candidate_ready",
            "unverifiable",
            "fatal_failure",
            "exhausted",
            "cancelled",
        }
    ),
    "accepted": frozenset(),
    "unverifiable": frozenset(),
    "fatal_failure": frozenset(),
    "exhausted": frozenset(),
    "cancelled": frozenset(),
}


@dataclass
class AgentControlState:
    """Host-owned state for one bounded Agent run."""

    state: RunState = "understanding"
    message: str | None = None
    failure_kind: FailureKind | None = None
    clarification_options: list[str] = field(default_factory=list)

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_RUN_STATES

    def transition(
        self,
        state: RunState,
        *,
        message: str | None = None,
        failure_kind: FailureKind | None = None,
    ) -> None:
        if state == self.state:
            if message is not None:
                self.message = message
            if failure_kind is not None:
                self.failure_kind = failure_kind
            return
        if state not in _RUN_STATE_TRANSITIONS[self.state]:
            raise ValueError(f"invalid Agent state transition: {self.state} -> {state}")
        self.state = state
        self.message = message
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class RequirementSpec:
    """Structured, JSON-compatible understanding of one PLC requirement."""

    goal: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    timing_rules: list[str] = field(default_factory=list)
    state_rules: list[str] = field(default_factory=list)
    safety_rules: list[str] = field(default_factory=list)
    observable_assertions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.goal, str) or not self.goal.strip():
            errors.append("goal must be a non-empty string")
        list_fields = (
            "inputs",
            "outputs",
            "timing_rules",
            "state_rules",
            "safety_rules",
            "observable_assertions",
            "assumptions",
            "open_questions",
        )
        for name in list_fields:
            value = getattr(self, name)
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                errors.append(f"{name} must be a list of non-empty strings")
        if not self.open_questions:
            if not self.outputs:
                errors.append("outputs must identify at least one observable result")
            if not self.observable_assertions:
                errors.append("observable_assertions must contain at least one behavior assertion")
        return errors

    @property
    def ready(self) -> bool:
        return not self.validation_errors() and not self.open_questions

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequirementContext:
    """Host-owned requirement state shared by the P1 tools and Agent."""

    spec: RequirementSpec | None = None

    @property
    def ready(self) -> bool:
        return bool(self.spec and self.spec.ready)


@dataclass(frozen=True)
class M5Request:
    task: str
    max_attempts: int = 3
    source_filename: str = "candidate.st"
    max_actions: int = 8

    def validate(self) -> str | None:
        if not isinstance(self.task, str) or not self.task.strip():
            return "task must be a non-empty string"
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            return "max_attempts must be an integer"
        if not 1 <= self.max_attempts <= 3:
            return "max_attempts must be between 1 and 3"
        if not isinstance(self.max_actions, int) or isinstance(self.max_actions, bool):
            return "max_actions must be an integer"
        if not 2 <= self.max_actions <= 12:
            return "max_actions must be between 2 and 12"
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
    state: RunState | None = None
    requirement_spec: dict[str, Any] | None = None
    clarification_options: list[str] = field(default_factory=list)
    model_final_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attempts"] = [attempt.to_dict() for attempt in self.attempts]
        return payload

