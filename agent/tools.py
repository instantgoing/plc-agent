"""smolagents Tool adapters over the stable plc_tools contracts."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from plc_tools import check_st_text, compile_st, get_plc_status, start_plc, stop_plc, verify_plan

from ._smolagents import Tool
from .contracts import AttemptRecord, FailureKind


MAX_ST_CHARS = 40_000
MAX_PLAN_STEPS = 64
MAX_FEEDBACK_CHARS = 8_000


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


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
    return None


class CandidateEvaluator:
    """Deterministic, serial candidate evaluation state."""

    def __init__(self, *, max_attempts: int, source_filename: str):
        self.max_attempts = max_attempts
        self.source_filename = Path(source_filename).name
        self.attempts: list[AttemptRecord] = []
        self.last_result: dict[str, Any] | None = None
        self.last_st_code: str | None = None
        self.last_plan: dict[str, Any] | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.last_result and self.last_result.get("accepted"))

    @property
    def fatal(self) -> bool:
        return bool(self.last_result and not self.last_result.get("retryable", True))

    def _record(self, record: AttemptRecord, *, accepted: bool) -> dict[str, Any]:
        record.accepted = accepted
        self.attempts.append(record)
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
            "attempts_remaining": max(0, self.max_attempts - len(self.attempts)),
            "retryable": not record.feedback.get("fatal", False),
        }
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

        record = AttemptRecord(attempt_number, digest, "check")
        if not isinstance(st_code, str) or not st_code.strip():
            record.feedback = _failure_feedback(
                kind="model_output_invalid",
                phase="check",
                detail={"error": "st_code must be a non-empty string"},
            )
            return self._record(record, accepted=False)
        if len(st_code) > MAX_ST_CHARS:
            record.feedback = _failure_feedback(
                kind="model_output_invalid",
                phase="check",
                detail={"error": f"st_code exceeds {MAX_ST_CHARS} characters"},
            )
            return self._record(record, accepted=False)
        plan_error = _validate_plan(verification_plan)
        if plan_error:
            record.feedback = _failure_feedback(
                kind="model_output_invalid",
                phase="check",
                detail={"error": plan_error},
            )
            return self._record(record, accepted=False)

        self.last_st_code = st_code
        self.last_plan = verification_plan

        try:
            status = get_plc_status()
        except Exception as exc:
            record.phase = "failed"
            record.feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="check",
                detail={"error": f"status tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                retryable=False,
            )
            record.feedback["fatal"] = True
            return self._record(record, accepted=False)
        status_payload = _json_value(status)
        if not status.success:
            record.phase = "failed"
            record.feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="check",
                detail={"status": status_payload, "fatal": True},
                retryable=False,
            )
            record.feedback["fatal"] = True
            return self._record(record, accepted=False)
        if status.actual_status == "RUNNING":
            record.phase = "failed"
            record.feedback = _failure_feedback(
                kind="runtime_busy",
                phase="check",
                detail={"status": status_payload, "fatal": True},
                retryable=False,
            )
            record.feedback["fatal"] = True
            return self._record(record, accepted=False)

        try:
            check = check_st_text(st_code, filename=self.source_filename)
        except Exception as exc:
            record.phase = "failed"
            record.feedback = _failure_feedback(
                kind="tool_unavailable",
                phase="check",
                detail={"error": f"check tool failed: {type(exc).__name__}: {exc}", "fatal": True},
                retryable=False,
            )
            record.feedback["fatal"] = True
            return self._record(record, accepted=False)
        record.check_result = _truncate(_json_value(check))
        if not check.success:
            record.phase = "failed"
            kind: FailureKind = "tool_unavailable" if check.tool_error else "candidate_check_failed"
            fatal = bool(check.tool_error)
            record.feedback = _failure_feedback(
                kind=kind,
                phase="check",
                detail={"check": record.check_result, "fatal": fatal},
                retryable=not fatal,
            )
            record.feedback["fatal"] = fatal
            return self._record(record, accepted=False)

        with tempfile.TemporaryDirectory(prefix="plc-agent-m5-") as directory:
            source = Path(directory) / self.source_filename
            source.write_text(st_code, encoding="utf-8")
            record.phase = "compile"
            try:
                compile_result = compile_st(source)
            except Exception as exc:
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
                    if verification.tool_error:
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
        return self._record(record, accepted=accepted)


class EvaluateCandidateTool(Tool):
    name = "evaluate_candidate"
    description = (
        "Submit a complete PLC Structured Text program and a verification plan. "
        "The tool performs real MatIEC/OpenPLC compilation and behavior verification."
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


def format_json(value: Any) -> str:
    """Stable JSON formatting for smolagents observations and CLI output."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


__all__ = ["CandidateEvaluator", "EvaluateCandidateTool", "format_json"]
