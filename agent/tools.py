"""smolagents Tool adapters over the stable plc_tools contracts."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Any

from plc_tools import check_st_text, compile_st, get_plc_status, start_plc, stop_plc, verify_plan

from ._smolagents import Tool
from .contracts import (
    AgentControlState,
    AttemptRecord,
    FailureKind,
    RequirementContext,
    RequirementSpec,
)
from .events import EventEmitter


MAX_ST_CHARS = 40_000
MAX_PLAN_STEPS = 64
MAX_FEEDBACK_CHARS = 8_000
_PLC_ADDRESS = re.compile(r"%[IQM][XBWDL]?\d+(?:\.\d+)?", re.IGNORECASE)


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _candidate_key(st_code: str, verification_plan: dict[str, Any]) -> str:
    canonical_plan = json.dumps(
        verification_plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(f"{st_code}\n---verification-plan---\n{canonical_plan}")


def _json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


def _truncate(value: Any, limit: int = MAX_FEEDBACK_CHARS) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, dict):
        return {key: _truncate(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value]
    return value


def _failure_feedback(
    *,
    kind: FailureKind,
    phase: str,
    detail: dict[str, Any] | None = None,
    retryable: bool = True,
    next_action: str | None = None,
) -> dict[str, Any]:
    feedback: dict[str, Any] = {
        "accepted": False,
        "failure_kind": kind,
        "phase": phase,
        "retryable": retryable,
        "diagnostics": [],
    }
    if detail:
        feedback.update(_truncate(detail))
    feedback["next_action"] = next_action or (
        "Submit a complete repaired st_code and verification_plan, not only an explanation."
        if retryable
        else "Stop candidate repair and report this environment or configuration failure."
    )
    return feedback


def _validate_plan(plan: Any) -> str | None:
    if not isinstance(plan, dict):
        return "verification_plan must be an object"
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return "verification_plan.steps must be a non-empty list"
    if len(steps) > MAX_PLAN_STEPS:
        return f"verification_plan.steps exceeds {MAX_PLAN_STEPS} steps"
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return f"verification_plan step {index} must be an object"
        inputs = step.get("inputs", {})
        expected = step.get("expected", step.get("expect", {}))
        if not isinstance(inputs, dict) or not isinstance(expected, dict):
            return f"verification_plan step {index} inputs and expected must be objects"
        if not expected:
            return f"verification_plan step {index} must assert at least one expected output"
        if any(not isinstance(name, str) or not name.strip() for name in (*inputs, *expected)):
            return f"verification_plan step {index} variable names must be non-empty strings"
        for timing in ("time_ms", "settle_ms"):
            value = step.get(timing)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                return f"verification_plan step {index} {timing} must be a nonnegative integer"
    return None


class CandidateEvaluator:
    """Deterministic, serial candidate evaluation state."""

    def __init__(
        self,
        *,
        max_attempts: int,
        source_filename: str,
        events: EventEmitter | None = None,
        cancel_event: Event | None = None,
    ):
        self.max_attempts = max_attempts
        self.source_filename = Path(source_filename).name
        self.attempts: list[AttemptRecord] = []
        self.last_result: dict[str, Any] | None = None
        self.last_st_code: str | None = None
        self.last_plan: dict[str, Any] | None = None
        self.last_validation: dict[str, Any] | None = None
        self._validated_candidate_key: str | None = None
        self._validated_check_result: dict[str, Any] | None = None
        self.events = events or EventEmitter()
        self.cancel_event = cancel_event

    def _cancel_requested(self) -> bool:
        return bool(self.cancel_event and self.cancel_event.is_set())

    @property
    def accepted(self) -> bool:
        return bool(self.last_result and self.last_result.get("accepted"))

    @property
    def fatal(self) -> bool:
        return bool(
            self.last_result
            and self.last_result.get("feedback", {}).get("fatal", False)
        )

    @property
    def exhausted(self) -> bool:
        return bool(
            len(self.attempts) >= self.max_attempts
            and not self.accepted
            and not self.fatal
        )

    def _reject_submission(
        self,
        *,
        digest: str,
        feedback: dict[str, Any],
        submission_rejected: bool = True,
    ) -> dict[str, Any]:
        """Reject malformed model arguments without spending a PLC attempt."""

        result = {
            "accepted": False,
            "attempt": len(self.attempts) + 1,
            "st_code_digest": digest,
            "check_result": None,
            "compile_result": None,
            "start_result": None,
            "verify_result": None,
            "stop_result": None,
            "feedback": feedback,
            "attempts_used": len(self.attempts),
            "attempts_remaining": max(0, self.max_attempts - len(self.attempts)),
            "retryable": bool(feedback.get("retryable", True)),
            "submission_rejected": submission_rejected,
            "budget_exhausted": False,
        }
        self.last_result = result
        return result

    def _record(self, record: AttemptRecord, *, accepted: bool) -> dict[str, Any]:
        record.accepted = accepted
        self.attempts.append(record)
        attempts_remaining = max(0, self.max_attempts - len(self.attempts))
        fatal = bool(record.feedback.get("fatal", False))
        cancelled = record.feedback.get("failure_kind") == "cancelled"
        budget_exhausted = not accepted and not fatal and not cancelled and attempts_remaining == 0
        if budget_exhausted:
            record.feedback["next_action"] = (
                "The PLC candidate budget is exhausted. Report the last failure without "
                "submitting another candidate."
            )
        result = {
            "accepted": accepted,
            "attempt": record.attempt,
            "st_code_digest": record.st_code_digest,
            "check_result": record.check_result,
            "compile_result": record.compile_result,
            "start_result": record.start_result,
            "verify_result": record.verify_result,
            "stop_result": record.stop_result,
            "feedback": record.feedback,
            "attempts_used": len(self.attempts),
            "attempts_remaining": attempts_remaining,
            "retryable": not accepted and not fatal and not cancelled and not budget_exhausted,
            "submission_rejected": False,
            "budget_exhausted": budget_exhausted,
        }
        self.last_result = result
        return result

    def validate(
        self,
        st_code: str,
        verification_plan: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Run structural validation and the real ST checker without touching Runtime."""

        del summary
        digest = _digest(st_code) if isinstance(st_code, str) else ""
        if self._cancel_requested():
            return {"valid": False, "cancelled": True, "feedback": _failure_feedback(
                kind="cancelled", phase="validate", retryable=False,
                next_action="The user cancelled this turn.",
            )}
        self._validated_candidate_key = None
        self._validated_check_result = None

        error: str | None = None
        if not isinstance(st_code, str) or not st_code.strip():
            error = "st_code must be a non-empty string"
        elif len(st_code) > MAX_ST_CHARS:
            error = f"st_code exceeds {MAX_ST_CHARS} characters"
        else:
            error = _validate_plan(verification_plan)
        if error:
            self.events.emit("check_failed", {"reason": error, "st_code_digest": digest})
            result = self._reject_submission(
                digest=digest,
                feedback=_failure_feedback(
                    kind="model_output_invalid",
                    phase="validate",
                    detail={"error": error},
                    next_action="Correct the candidate arguments and call validate_candidate again.",
                ),
            )
            result["valid"] = False
            self.last_validation = result
            return result

        self.events.emit("candidate_generated", {"st_code_digest": digest})
        self.events.emit("check_started", {"st_code_digest": digest})
        try:
            check = check_st_text(st_code, filename=self.source_filename)
        except Exception as exc:
            feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="validate",
                detail={
                    "error": f"check tool failed: {type(exc).__name__}: {exc}",
                    "fatal": True,
                },
                retryable=False,
            )
            feedback["fatal"] = True
            result = self._reject_submission(digest=digest, feedback=feedback)
            result.update({"valid": False, "retryable": False})
            self.last_validation = result
            self.events.emit("check_failed", {"reason": feedback, "st_code_digest": digest})
            return result

        check_result = _truncate(_json_value(check))
        if not check.success:
            fatal = bool(check.tool_error)
            kind: FailureKind = "tool_unavailable" if fatal else "candidate_check_failed"
            feedback = _failure_feedback(
                kind=kind,
                phase="validate",
                detail={"check": check_result, "fatal": fatal},
                retryable=not fatal,
                next_action=(
                    "Repair the ST diagnostics and call validate_candidate again."
                    if not fatal
                    else "Report the checker environment failure without starting Runtime."
                ),
            )
            feedback["fatal"] = fatal
            result = self._reject_submission(digest=digest, feedback=feedback)
            result.update({"valid": False, "check_result": check_result, "retryable": not fatal})
            self.last_validation = result
            self.events.emit("check_failed", {"reason": feedback, "st_code_digest": digest})
            return result

        key = _candidate_key(st_code, verification_plan)
        self._validated_candidate_key = key
        self._validated_check_result = check_result
        result = {
            "valid": True,
            "accepted": False,
            "candidate_key": key,
            "st_code_digest": digest,
            "check_result": check_result,
            "feedback": {
                "phase": "validate",
                "next_action": (
                    "Call evaluate_candidate with exactly the same st_code and verification_plan."
                ),
            },
            "attempts_used": len(self.attempts),
            "attempts_remaining": max(0, self.max_attempts - len(self.attempts)),
            "retryable": True,
            "submission_rejected": False,
            "budget_exhausted": False,
        }
        self.last_validation = result
        self.last_result = result
        return result

    def evaluate(
        self,
        st_code: str,
        verification_plan: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        del summary  # The evaluator is intentionally independent of model prose.
        attempt_number = len(self.attempts) + 1
        digest = _digest(st_code) if isinstance(st_code, str) else ""
        if attempt_number > self.max_attempts:
            feedback = _failure_feedback(
                kind="attempt_limit_reached",
                phase="failed",
                retryable=False,
                detail={"fatal": True},
                next_action="The bounded repair budget is exhausted. Report failure.",
            )
            result = {
                "accepted": False,
                "attempt": attempt_number,
                "st_code_digest": digest,
                "check_result": None,
                "compile_result": None,
                "start_result": None,
                "verify_result": None,
                "stop_result": None,
                "feedback": feedback,
                "attempts_used": len(self.attempts),
                "attempts_remaining": 0,
                "retryable": False,
            }
            self.last_result = result
            return result

        if (
            not isinstance(st_code, str)
            or not isinstance(verification_plan, dict)
            or _candidate_key(st_code, verification_plan) != self._validated_candidate_key
        ):
            return self._reject_submission(
                digest=digest,
                feedback=_failure_feedback(
                    kind="candidate_not_validated",
                    phase="evaluate",
                    detail={"error": "candidate differs from the last successful preflight validation"},
                    next_action="Call validate_candidate, then evaluate the exact validated candidate.",
                ),
            )

        if self._cancel_requested():
            return self._reject_submission(
                digest=digest,
                feedback=_failure_feedback(
                    kind="cancelled", phase="runtime_preflight", retryable=False,
                    next_action="The user cancelled this turn before Runtime execution.",
                ),
                submission_rejected=False,
            )

        try:
            status = get_plc_status()
        except Exception as exc:
            feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="runtime_preflight",
                detail={"error": f"status tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                retryable=False,
            )
            feedback["fatal"] = True
            return self._reject_submission(
                digest=digest,
                feedback=feedback,
                submission_rejected=False,
            )
        status_payload = _json_value(status)
        if not status.success:
            feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="runtime_preflight",
                detail={"status": status_payload, "fatal": True},
                retryable=False,
            )
            feedback["fatal"] = True
            return self._reject_submission(
                digest=digest,
                feedback=feedback,
                submission_rejected=False,
            )
        if status.actual_status == "RUNNING":
            feedback = _failure_feedback(
                kind="runtime_busy",
                phase="runtime_preflight",
                detail={"status": status_payload, "fatal": True},
                retryable=False,
            )
            feedback["fatal"] = True
            return self._reject_submission(
                digest=digest,
                feedback=feedback,
                submission_rejected=False,
            )

        if self._cancel_requested():
            return self._reject_submission(
                digest=digest,
                feedback=_failure_feedback(
                    kind="cancelled", phase="runtime_preflight", retryable=False,
                    next_action="The user cancelled this turn before compilation.",
                ),
                submission_rejected=False,
            )

        record = AttemptRecord(
            attempt_number,
            digest,
            "compile",
            check_result=self._validated_check_result,
        )
        self.last_st_code = st_code
        self.last_plan = verification_plan

        self.events.emit("compile_started", {"attempt": attempt_number, "st_code_digest": digest})
        with tempfile.TemporaryDirectory(prefix="plc-agent-m5-") as directory:
            source = Path(directory) / self.source_filename
            source.write_text(st_code, encoding="utf-8")
            record.phase = "compile"
            try:
                compile_result = compile_st(source)
            except Exception as exc:
                if self._cancel_requested():
                    record.phase = "cancelled"
                    record.feedback = _failure_feedback(
                        kind="cancelled", phase="compile", retryable=False,
                        detail={"compile_error": f"{type(exc).__name__}: {exc}"},
                        next_action="The user cancelled this turn during compilation.",
                    )
                    try:
                        stopped = stop_plc()
                        record.stop_result = _truncate(_json_value(stopped))
                    except Exception as stop_exc:
                        record.stop_result = {
                            "success": False,
                            "tool_error": f"{type(stop_exc).__name__}: {stop_exc}",
                        }
                    self.events.emit("cleanup_completed", {"stop_result": record.stop_result})
                    if not record.stop_result.get("success"):
                        record.feedback["cleanup_error"] = record.stop_result
                    return self._record(record, accepted=False)
                record.phase = "failed"
                record.feedback = _failure_feedback(
                    kind="tool_unavailable",
                    phase="compile",
                    detail={"error": f"compile tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                    retryable=False,
                )
                record.feedback["fatal"] = True
                return self._record(record, accepted=False)
        record.compile_result = _truncate(_json_value(compile_result))
        if self._cancel_requested():
            record.phase = "cancelled"
            record.feedback = _failure_feedback(
                kind="cancelled", phase="compile", retryable=False,
                next_action="The user cancelled this turn after compilation.",
            )
            try:
                stopped = stop_plc()
                record.stop_result = _truncate(_json_value(stopped))
            except Exception as exc:
                record.stop_result = {"success": False, "tool_error": f"{type(exc).__name__}: {exc}"}
            self.events.emit("cleanup_completed", {"stop_result": record.stop_result})
            if not record.stop_result.get("success"):
                record.feedback["cleanup_error"] = record.stop_result
            return self._record(record, accepted=False)

        if not compile_result.success:
            record.phase = "failed"
            fatal = bool(compile_result.tool_error)
            kind = "tool_unavailable" if fatal else "candidate_compile_failed"
            record.feedback = _failure_feedback(
                kind=kind,
                phase="compile",
                detail={"compile": record.compile_result, "fatal": fatal},
                retryable=not fatal,
            )
            record.feedback["fatal"] = fatal
            return self._record(record, accepted=False)

        started = False
        cleanup_required = True
        accepted = False
        try:
            record.phase = "start"
            try:
                start_result = start_plc()
            except Exception as exc:
                record.phase = "failed"
                record.feedback = _failure_feedback(
                    kind="tool_unavailable",
                    phase="start",
                    detail={"error": f"start tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                    retryable=False,
                )
                record.feedback["fatal"] = True
                return self._record(record, accepted=False)
            record.start_result = _truncate(_json_value(start_result))
            started = start_result.success
            if started:
                self.events.emit("runtime_started", {"attempt": attempt_number})
            if not start_result.success:
                record.phase = "failed"
                fatal = bool(start_result.tool_error)
                kind = "tool_unavailable" if fatal else "runtime_start_failed"
                record.feedback = _failure_feedback(
                    kind=kind,
                    phase="start",
                    detail={"start": record.start_result, "fatal": fatal},
                    retryable=not fatal,
                )
                record.feedback["fatal"] = fatal
            else:
                record.phase = "verify"
                try:
                    if self.cancel_event is not None or self.events.callback is not None:
                        verification = verify_plan(
                            verification_plan,
                            cancel_requested=self._cancel_requested,
                            on_step=lambda step: self.events.emit(
                                "verification_step", _json_value(step)
                            ),
                        )
                    else:
                        verification = verify_plan(verification_plan)
                except Exception as exc:
                    record.phase = "failed"
                    record.feedback = _failure_feedback(
                        kind="tool_unavailable",
                        phase="verify",
                        detail={"error": f"verify tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                        retryable=False,
                    )
                    record.feedback["fatal"] = True
                    verification = None
                if verification is None:
                    pass
                else:
                    record.verify_result = _truncate(_json_value(verification))
                    if (
                        verification.cleanup_result is not None
                        and not verification.cleanup_result.get("success", False)
                    ):
                        record.phase = "failed"
                        record.feedback = _failure_feedback(
                            kind="tool_unavailable", phase="verify", retryable=False,
                            detail={"verification": record.verify_result, "fatal": True},
                            next_action="Forced-variable release failed; report the cleanup failure.",
                        )
                        record.feedback["fatal"] = True
                    elif verification.cancelled:
                        record.phase = "cancelled"
                        record.feedback = _failure_feedback(
                            kind="cancelled", phase="verify", retryable=False,
                            detail={"verification": record.verify_result},
                            next_action="The user cancelled this turn; Runtime cleanup is in progress.",
                        )
                    elif verification.tool_error:
                        record.phase = "failed"
                        record.feedback = _failure_feedback(
                            kind="tool_unavailable",
                            phase="verify",
                            detail={"verification": record.verify_result, "fatal": True},
                            retryable=False,
                        )
                        record.feedback["fatal"] = True
                    elif not verification.passed:
                        record.phase = "failed"
                        record.feedback = _failure_feedback(
                            kind="behavior_verification_failed",
                            phase="verify",
                            detail={"verification": record.verify_result},
                        )
                    else:
                        record.phase = "accepted"
                        record.feedback = {
                            "accepted": True,
                            "phase": "verify",
                            "next_action": "Call final_answer with the verified result.",
                        }
                        accepted = True
        finally:
            if cleanup_required:
                try:
                    stopped = stop_plc()
                except Exception as exc:
                    stopped = None
                    record.stop_result = {"success": False, "tool_error": f"{type(exc).__name__}: {exc}"}
                else:
                    record.stop_result = _truncate(_json_value(stopped))
                if stopped is None or not stopped.success:
                    accepted = False
                    record.phase = "failed"
                    record.feedback = _failure_feedback(
                        kind="tool_unavailable",
                        phase="failed",
                        detail={"stop": record.stop_result, "fatal": True},
                        retryable=False,
                    )
                    record.feedback["fatal"] = True
                self.events.emit("cleanup_completed", {
                    "stop_result": record.stop_result,
                    "release_result": (
                        record.verify_result.get("cleanup_result") if record.verify_result else None
                    ),
                })
        return self._record(record, accepted=accepted)


class SubmitRequirementSpecTool(Tool):
    name = "submit_requirement_spec"
    description = (
        "Submit the structured understanding of the PLC requirement before generating or "
        "validating code. If open_questions is non-empty, ask the user instead of proceeding."
    )
    inputs = {
        "goal": {"type": "string", "description": "Concise requested PLC behavior."},
        "inputs": {"type": "array", "description": "Known PLC inputs and addresses."},
        "outputs": {"type": "array", "description": "Known observable outputs and addresses."},
        "timing_rules": {"type": "array", "description": "Timing and timeout rules."},
        "state_rules": {"type": "array", "description": "Latch, reset, and transition rules."},
        "safety_rules": {"type": "array", "description": "Fail-safe and interlock rules."},
        "observable_assertions": {
            "type": "array",
            "description": "Behavior assertions that the verification plan can observe.",
        },
        "assumptions": {"type": "array", "description": "Explicit, non-safety assumptions."},
        "open_questions": {
            "type": "array",
            "description": "Missing facts that require user confirmation.",
        },
    }
    output_type = "object"

    def __init__(self, requirements: RequirementContext, control: AgentControlState):
        self.requirements = requirements
        self.control = control
        self.is_initialized = True

    def forward(
        self,
        goal: str,
        inputs: list[str],
        outputs: list[str],
        timing_rules: list[str],
        state_rules: list[str],
        safety_rules: list[str],
        observable_assertions: list[str],
        assumptions: list[str],
        open_questions: list[str],
    ) -> dict[str, Any]:
        spec = RequirementSpec(
            goal=goal,
            inputs=inputs,
            outputs=outputs,
            timing_rules=timing_rules,
            state_rules=state_rules,
            safety_rules=safety_rules,
            observable_assertions=observable_assertions,
            assumptions=assumptions,
            open_questions=open_questions,
        )
        errors = spec.validation_errors()
        if errors:
            return {
                "ready": False,
                "errors": errors,
                "next_action": "Correct the RequirementSpec and submit it again.",
            }
        self.requirements.spec = spec
        if spec.ready:
            self.control.transition(
                "requirement_ready",
                message="RequirementSpec is complete enough for candidate generation.",
            )
            next_action = "Generate a candidate and call validate_candidate."
        else:
            next_action = "Call ask_user with one concise question covering the open questions."
        return {
            "ready": spec.ready,
            "requirement_spec": spec.to_dict(),
            "next_action": next_action,
        }


class ValidateCandidateTool(Tool):
    name = "validate_candidate"
    description = (
        "Cheap candidate preflight: validate ST and verification-plan structure and run the "
        "real ST checker. This never starts Runtime and never consumes a Runtime attempt."
    )
    inputs = {
        "st_code": {"type": "string", "description": "Complete IEC 61131-3 Structured Text program."},
        "verification_plan": {
            "type": "object",
            "description": "Object with a non-empty steps list containing inputs and expected values.",
        },
        "summary": {"type": "string", "nullable": True, "description": "Optional short candidate summary."},
    }
    output_type = "object"

    def __init__(self, evaluator: CandidateEvaluator):
        self.evaluator = evaluator
        self.is_initialized = True

    def forward(
        self,
        st_code: str,
        verification_plan: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluator.validate(st_code, verification_plan, summary)


class EvaluateCandidateTool(Tool):
    name = "evaluate_candidate"
    description = (
        "Evaluate the exact candidate most recently accepted by validate_candidate. "
        "This performs real compilation, Runtime start, behavior verification, and cleanup, "
        "and consumes one Runtime attempt."
    )
    inputs = {
        "st_code": {"type": "string", "description": "Complete IEC 61131-3 Structured Text program."},
        "verification_plan": {
            "type": "object",
            "description": "Object with a non-empty steps list containing inputs and expected values.",
        },
        "summary": {"type": "string", "nullable": True, "description": "Optional short candidate summary."},
    }
    output_type = "object"

    def __init__(self, evaluator: CandidateEvaluator):
        self.evaluator = evaluator
        self.is_initialized = True

    def forward(
        self,
        st_code: str,
        verification_plan: dict[str, Any],
        summary: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluator.evaluate(st_code, verification_plan, summary)


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Pause this run and ask one concise question when required PLC addresses, "
        "timing, state, safety, or observable behavior is missing or ambiguous. "
        "Offer two to four safe semantic choices when possible. Never suggest "
        "an I/O address that the user has not already supplied."
    )
    inputs = {
        "question": {
            "type": "string",
            "description": "One concise question grouping only the information needed to continue.",
        },
        "choices": {
            "type": "array",
            "nullable": True,
            "description": "Zero to four safe choices. Do not invent addresses; omit choices if addresses are unknown.",
        },
    }
    output_type = "object"

    def __init__(self, control: AgentControlState, source_text: str):
        self.control = control
        self.known_addresses = {
            address.upper() for address in _PLC_ADDRESS.findall(source_text)
        }
        self.is_initialized = True

    def forward(self, question: str, choices: list[str] | None = None) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("question must be non-empty")
        if choices is None:
            choices = []
        if (
            not isinstance(choices, list)
            or len(choices) > 4
            or any(not isinstance(choice, str) or not choice.strip() for choice in choices)
        ):
            raise ValueError("choices must contain zero to four non-empty strings")
        # Model-proposed examples are not user-confirmed PLC wiring. Drop any
        # choice that introduces an address absent from the requirement model.
        choices = [
            choice for choice in choices
            if all(
                address.upper() in self.known_addresses
                for address in _PLC_ADDRESS.findall(choice)
            )
        ]
        self.control.transition("needs_user_input", message=question)
        self.control.clarification_options = choices
        return {
            "state": self.control.state,
            "question": question,
            "choices": choices,
            "next_action": "Call final_answer with exactly this question.",
        }


class ReportUnverifiableTool(Tool):
    name = "report_unverifiable"
    description = (
        "End unsuccessfully when the requested behavior cannot be observed or verified "
        "by the available PLC contracts."
    )
    inputs = {
        "reason": {
            "type": "string",
            "description": "Concise reason the requirement cannot be behavior-verified.",
        }
    }
    output_type = "object"

    def __init__(self, control: AgentControlState):
        self.control = control
        self.is_initialized = True

    def forward(self, reason: str) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise ValueError("reason must be non-empty")
        self.control.transition(
            "unverifiable",
            message=reason,
            failure_kind="unverifiable_requirement",
        )
        return {
            "state": self.control.state,
            "reason": reason,
            "next_action": "Call final_answer with this reason without claiming success.",
        }


class ReportFailureTool(Tool):
    name = "report_failure"
    description = (
        "End unsuccessfully when the Agent cannot safely continue for a reason that is "
        "not a missing user detail and not an unverifiable requirement."
    )
    inputs = {
        "reason": {
            "type": "string",
            "description": "Concise non-success reason. Never use this to claim correctness.",
        }
    }
    output_type = "object"

    def __init__(self, control: AgentControlState):
        self.control = control
        self.is_initialized = True

    def forward(self, reason: str) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise ValueError("reason must be non-empty")
        self.control.transition(
            "fatal_failure",
            message=reason,
            failure_kind="agent_reported_failure",
        )
        return {
            "state": self.control.state,
            "reason": reason,
            "next_action": "Call final_answer with this reason without claiming success.",
        }


def format_json(value: Any) -> str:
    """Stable JSON formatting for smolagents observations and CLI output."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


__all__ = [
    "AskUserTool",
    "CandidateEvaluator",
    "EvaluateCandidateTool",
    "ReportFailureTool",
    "ReportUnverifiableTool",
    "SubmitRequirementSpecTool",
    "ValidateCandidateTool",
    "format_json",
]
