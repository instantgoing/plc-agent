"""PLC-specialized smolagents agent and the public M5 repair-loop entrypoint."""

from __future__ import annotations

from typing import Any
from threading import Event

from ._smolagents import (
    AgentExecutionError, AgentParsingError, AgentToolCallError, OpenAIModel, ToolCallingAgent,
)
from .contracts import (
    AgentControlState,
    FailureKind,
    M5Request,
    M5Result,
    RequirementContext,
)
from .model import (
    ModelConfig,
    ModelConfigurationError,
    ModelPreflightError,
    build_model,
    load_model_config,
    preflight_model,
)
from .events import EventCallback, EventEmitter
from .prompts import FINAL_ANSWER_INSTRUCTIONS, PLC_SYSTEM_INSTRUCTIONS
from .tools import (
    AskUserTool,
    CandidateEvaluator,
    EvaluateCandidateTool,
    ReportFailureTool,
    ReportUnverifiableTool,
    SubmitRequirementSpecTool,
    ValidateCandidateTool,
)


def _final_answer_is_allowed(answer: Any, memory: Any, *, agent: "PLCToolCallingAgent") -> bool:
    del answer, memory
    return agent.control.terminal


class PLCToolCallingAgent(ToolCallingAgent):
    """A ToolCallingAgent constrained to one serial PLC candidate evaluator."""

    def __init__(
        self,
        *,
        evaluator: CandidateEvaluator,
        control: AgentControlState,
        requirements: RequirementContext,
        events: EventEmitter,
        cancel_event: Event | None,
        model: Any,
        max_actions: int,
        source_text: str,
        **kwargs: Any,
    ):
        self.evaluator = evaluator
        self.control = control
        self.requirements = requirements
        self.events = events
        self.cancel_event = cancel_event
        instructions = kwargs.pop("instructions", "")
        combined_instructions = "\n\n".join(
            part for part in (PLC_SYSTEM_INSTRUCTIONS, instructions, FINAL_ANSWER_INSTRUCTIONS) if part
        )
        super().__init__(
            tools=[
                SubmitRequirementSpecTool(requirements, control),
                ValidateCandidateTool(evaluator),
                EvaluateCandidateTool(evaluator),
                AskUserTool(control, source_text),
                ReportUnverifiableTool(control),
                ReportFailureTool(control),
            ],
            model=model,
            instructions=combined_instructions,
            add_base_tools=False,
            planning_interval=None,
            stream_outputs=False,
            max_tool_threads=1,
            max_steps=max_actions,
            final_answer_checks=[_final_answer_is_allowed],
            return_full_result=True,
            **kwargs,
        )

    def process_tool_calls(self, chat_message: Any, memory_step: Any):
        """Reject parallel calls because compile/start/verify are stateful."""

        if chat_message.tool_calls is not None and len(chat_message.tool_calls) > 1:
            raise AgentExecutionError(
                "M5 accepts exactly one tool call per action; submit one candidate or one final answer.",
                self.logger,
            )
        yield from super().process_tool_calls(chat_message, memory_step)

    def execute_tool_call(self, tool_name: str, arguments: dict[str, str] | str) -> Any:
        """Record evaluator state and block further candidates after a fatal error."""

        if self.control.terminal and tool_name != "final_answer":
            self.events.emit("tool_call_rejected", {"tool": tool_name, "reason": "terminal_state"})
            return {
                "state": self.control.state,
                "message": self.control.message,
                "next_action": "Call final_answer; this run is already in a terminal state.",
            }
        if self.cancel_event is not None and self.cancel_event.is_set() and not self.control.terminal:
            self.control.transition(
                "cancelled", message="The user cancelled this turn.", failure_kind="cancelled"
            )
            self.events.emit("failed", {"failure_kind": "cancelled"})
            return {"state": "cancelled", "next_action": "Call final_answer without claiming success."}
        if tool_name in {"validate_candidate", "evaluate_candidate"} and not self.requirements.ready:
            self.events.emit("tool_call_rejected", {"tool": tool_name, "reason": "requirement_not_ready"})
            return {
                "accepted": False,
                "failure_kind": "model_output_invalid",
                "phase": "understanding",
                "next_action": "Call submit_requirement_spec before validating or evaluating code.",
            }
        if tool_name == "validate_candidate":
            self.control.transition("candidate_ready")
            self.control.transition("validating")
        elif tool_name == "evaluate_candidate":
            if self.control.state != "candidate_validated":
                self.events.emit("tool_call_rejected", {"tool": tool_name, "reason": "candidate_not_validated"})
                return {
                    "accepted": False,
                    "failure_kind": "candidate_not_validated",
                    "phase": "evaluate",
                    "next_action": "Call validate_candidate successfully before evaluate_candidate.",
                }
            self.control.transition("evaluating")
        try:
            result = super().execute_tool_call(tool_name, arguments)
        except Exception as exc:
            reason = (
                "schema_error" if isinstance(exc, AgentToolCallError)
                or isinstance(exc.__cause__, (TypeError, ValueError)) else "tool_exception"
            )
            self.events.emit("tool_call_rejected", {"tool": tool_name, "reason": reason})
            if tool_name in {"validate_candidate", "evaluate_candidate"} and self.control.state in {
                "validating",
                "evaluating",
            }:
                self.control.transition(
                    "repairable_failure",
                    message="The candidate tool call was invalid and can be corrected.",
                    failure_kind="model_output_invalid",
                )
            raise
        if tool_name == "submit_requirement_spec" and isinstance(result, dict):
            self.events.emit("requirement_analyzed", {
                "ready": bool(result.get("ready")),
                "open_questions": (
                    result.get("requirement_spec", {}).get("open_questions", [])
                ),
                "errors": result.get("errors", []),
            })
        elif tool_name == "ask_user" and isinstance(result, dict):
            self.events.emit("waiting_for_user", {
                "question": result.get("question"), "choices": result.get("choices", []),
            })
        elif tool_name in {"report_unverifiable", "report_failure"} and isinstance(result, dict):
            self.events.emit("failed", {
                "failure_kind": self.control.failure_kind,
                "reason": result.get("reason"),
            })
        elif tool_name == "validate_candidate" and isinstance(result, dict):
            self.state["plc_last_validation"] = result
            feedback = result.get("feedback") or {}
            failure_kind = PLCRepairAgent._failure_from_feedback(feedback)
            message = str(feedback.get("next_action") or "") or None
            if result.get("valid"):
                self.control.transition(
                    "candidate_validated",
                    message="Candidate passed the real ST preflight check.",
                )
            elif feedback.get("failure_kind") == "cancelled":
                self.control.transition("cancelled", message=message, failure_kind="cancelled")
                self.events.emit("failed", {"failure_kind": "cancelled"})
            elif feedback.get("fatal"):
                self.control.transition(
                    "fatal_failure",
                    message=message,
                    failure_kind=failure_kind or "tool_unavailable",
                )
                self.events.emit("failed", {"failure_kind": failure_kind or "tool_unavailable"})
            else:
                self.control.transition(
                    "repairable_failure",
                    message=message,
                    failure_kind=failure_kind or "model_output_invalid",
                )
                self.events.emit("repair_started", {"failure_kind": failure_kind})
        elif tool_name == "evaluate_candidate" and isinstance(result, dict):
            self.state["plc_last_evaluation"] = result
            self.state["plc_accepted"] = bool(result.get("accepted"))
            feedback = result.get("feedback") or {}
            failure_kind = PLCRepairAgent._failure_from_feedback(feedback)
            message = str(feedback.get("next_action") or "") or None
            if result.get("accepted"):
                self.control.transition("accepted", message="Real PLC behavior verification passed.")
                self.events.emit("accepted", {"attempt": result.get("attempt")})
            elif feedback.get("failure_kind") == "cancelled":
                self.control.transition("cancelled", message=message, failure_kind="cancelled")
                self.events.emit("failed", {"failure_kind": "cancelled"})
            elif feedback.get("fatal"):
                self.control.transition(
                    "fatal_failure",
                    message=message,
                    failure_kind=failure_kind or "tool_unavailable",
                )
                self.events.emit("failed", {"failure_kind": failure_kind})
            elif result.get("budget_exhausted"):
                self.control.transition(
                    "exhausted",
                    message=message,
                    failure_kind="attempt_limit_reached",
                )
                self.events.emit("failed", {"failure_kind": "attempt_limit_reached"})
            else:
                self.control.transition(
                    "repairable_failure",
                    message=message,
                    failure_kind=failure_kind,
                )
                self.events.emit("repair_started", {"failure_kind": failure_kind})
        self.state["plc_run_state"] = self.control.state
        self.state["plc_fatal"] = self.control.state == "fatal_failure"
        return result


class PLCRepairAgent:
    """Public M5 entrypoint wrapping one real smolagents-based agent run."""

    def __init__(
        self,
        *,
        model: Any | None = None,
        model_config: ModelConfig | None = None,
        provider: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self._model = model
        self._model_config = model_config
        self._model_overrides = {
            "provider": provider,
            "model_id": model_id,
            "api_key": api_key,
            "api_base": api_base,
        }

    def _build_model(self) -> tuple[Any, dict[str, str] | None]:
        if self._model is not None:
            model_id = getattr(self._model, "model_id", None)
            return self._model, {"provider": "custom", "model_id": str(model_id or "unknown")}
        if self._model_config is not None:
            return build_model(self._model_config), self._model_config.public_dict()
        overrides = {key: value for key, value in self._model_overrides.items() if value is not None}
        config = load_model_config(**overrides)
        return build_model(config), config.public_dict()

    @staticmethod
    def _failure_from_feedback(feedback: dict[str, Any] | None) -> FailureKind | None:
        if not feedback:
            return None
        candidate = feedback.get("failure_kind")
        known = {
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
        }
        return candidate if candidate in known else None

    @staticmethod
    def _classify_model_error(exc: Exception) -> FailureKind:
        text = f"{type(exc).__name__}: {exc}".lower()
        if any(marker in text for marker in (
            "authentication", "unauthorized", "forbidden", "api key", "401", "403"
        )):
            return "model_authentication_failed"
        if any(
            marker in text
            for marker in ("context window", "context length", "maximum context", "too many tokens")
        ):
            return "model_context_exceeded"
        if any(marker in text for marker in ("parse", "tool call", "invalid json", "jsondecode")):
            return "model_output_invalid"
        if ("tool" in text or "function" in text) and any(
            marker in text for marker in (
                "unsupported", "not support", "tool_choice", "function calling",
                "invalid", "unknown parameter", "not allowed", "not permitted",
            )
        ):
            return "model_tool_unsupported"
        if any(
            marker in text
            for marker in ("connection", "connecterror", "timeout", "timed out", "dns", "network")
        ):
            return "model_connection_failed"
        return "model_unavailable"

    @staticmethod
    def _final_message(run_result: Any, fallback: str) -> str:
        output = getattr(run_result, "output", None)
        if isinstance(output, str) and output.strip():
            return output.strip()
        return fallback

    @staticmethod
    def _record_parse_errors(agent: PLCToolCallingAgent, events: EventEmitter) -> None:
        for step in getattr(getattr(agent, "memory", None), "steps", []):
            if isinstance(getattr(step, "error", None), AgentParsingError):
                events.emit("tool_call_rejected", {"tool": None, "reason": "schema_error"})

    def run(
        self,
        request: M5Request | str,
        *,
        max_attempts: int | None = None,
        on_event: EventCallback | None = None,
        cancel_event: Event | None = None,
        session_id: str | None = None,
        turn: int = 1,
    ) -> M5Result:
        events = EventEmitter(on_event, session_id=session_id, turn=turn)
        if isinstance(request, str):
            request = M5Request(task=request, max_attempts=max_attempts or 3)
        elif max_attempts is not None:
            request = M5Request(
                task=request.task,
                max_attempts=max_attempts,
                source_filename=request.source_filename,
                max_actions=request.max_actions,
            )
        validation_error = request.validate()
        if validation_error:
            events.emit("failed", {"failure_kind": "invalid_request"})
            return M5Result(
                success=False,
                failure_kind="invalid_request",
                st_code=None,
                verification_plan=None,
                attempts=[],
                final_message=validation_error,
                model=None,
                state="fatal_failure",
                clarification_options=[],
            )

        try:
            model, model_info = self._build_model()
        except ModelConfigurationError as exc:
            events.emit("failed", {"failure_kind": "model_unavailable"})
            return M5Result(
                success=False,
                failure_kind="model_unavailable",
                st_code=None,
                verification_plan=None,
                attempts=[],
                final_message=str(exc),
                model=None,
                state="fatal_failure",
            )

        evaluator = CandidateEvaluator(
            max_attempts=request.max_attempts,
            source_filename=request.source_filename,
            events=events,
            cancel_event=cancel_event,
        )
        control = AgentControlState()
        requirements = RequirementContext()
        agent = PLCToolCallingAgent(
            evaluator=evaluator,
            control=control,
            requirements=requirements,
            events=events,
            cancel_event=cancel_event,
            model=model,
            max_actions=request.max_actions,
            source_text=request.task,
        )
        if isinstance(model, OpenAIModel):
            events.emit("model_preflight_started", {"model": model_info})
            try:
                preflight_model(model, agent.tools_and_managed_agents)
            except Exception as exc:
                failure_kind = (
                    exc.kind if isinstance(exc, ModelPreflightError)
                    else self._classify_model_error(exc)
                )
                if cancel_event is not None and cancel_event.is_set():
                    failure_kind = "cancelled"
                events.emit("failed", {"failure_kind": failure_kind, "phase": "model_preflight"})
                return M5Result(
                    success=False,
                    failure_kind=failure_kind,
                    st_code=None,
                    verification_plan=None,
                    attempts=[],
                    final_message=f"Model capability check failed: {exc}",
                    model=model_info,
                    state="cancelled" if failure_kind == "cancelled" else "fatal_failure",
                )
            events.emit("model_preflight_passed", {"model": model_info})
        try:
            run_result = agent.run(request.task, return_full_result=True)
        except Exception as exc:
            self._record_parse_errors(agent, events)
            if evaluator.accepted:
                return M5Result(
                    success=True,
                    failure_kind=None,
                    st_code=evaluator.last_st_code,
                    verification_plan=evaluator.last_plan,
                    attempts=evaluator.attempts,
                    final_message="Real PLC behavior verification passed.",
                    model=model_info,
                    state="accepted",
                    requirement_spec=(
                        requirements.spec.to_dict() if requirements.spec else None
                    ),
                    clarification_options=control.clarification_options,
                )
            failure_kind = self._classify_model_error(exc)
            if cancel_event is not None and cancel_event.is_set():
                failure_kind = "cancelled"
            if evaluator.last_result and evaluator.last_result.get("feedback"):
                failure_kind = self._failure_from_feedback(evaluator.last_result["feedback"]) or failure_kind
            if not control.terminal:
                control.transition(
                    "cancelled" if failure_kind == "cancelled" else "fatal_failure",
                    message=str(exc),
                    failure_kind=failure_kind,
                )
            events.emit("failed", {"failure_kind": failure_kind})
            return M5Result(
                success=False,
                failure_kind=failure_kind,
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=f"M5 agent execution failed: {type(exc).__name__}: {exc}",
                model=model_info,
                state=control.state,
                requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
                clarification_options=control.clarification_options,
            )

        self._record_parse_errors(agent, events)

        if evaluator.accepted:
            return M5Result(
                success=True,
                failure_kind=None,
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=self._final_message(
                    run_result,
                    "Real PLC behavior verification passed.",
                ),
                model=model_info,
                state="accepted",
                requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
                clarification_options=control.clarification_options,
            )

        if control.state == "needs_user_input":
            return M5Result(
                success=False,
                failure_kind=None,
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=control.message or "More information is required before PLC evaluation.",
                model=model_info,
                state=control.state,
                requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
                clarification_options=control.clarification_options,
                model_final_message=self._final_message(run_result, "") or None,
            )

        if control.state == "unverifiable":
            return M5Result(
                success=False,
                failure_kind="unverifiable_requirement",
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=self._final_message(
                    run_result,
                    control.message or "The requirement cannot be behavior-verified.",
                ),
                model=model_info,
                state=control.state,
                requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
                clarification_options=control.clarification_options,
            )

        if control.state == "cancelled":
            return M5Result(
                success=False,
                failure_kind="cancelled",
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=control.message or "The user cancelled this turn.",
                model=model_info,
                state="cancelled",
                requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
                clarification_options=control.clarification_options,
            )

        if not control.terminal:
            control.transition(
                "exhausted",
                message="The Agent action budget ended before reaching a terminal result.",
                failure_kind="action_limit_reached",
            )
            events.emit("failed", {"failure_kind": "action_limit_reached"})

        feedback = evaluator.last_result.get("feedback") if evaluator.last_result else None
        failure_kind = (
            control.failure_kind
            or self._failure_from_feedback(feedback)
            or "action_limit_reached"
        )
        fallback = control.message or (
            "The bounded repair budget ended without real behavior verification."
            if control.state == "exhausted"
            else "The candidate was not accepted by the real PLC evaluation pipeline."
        )
        return M5Result(
            success=False,
            failure_kind=failure_kind,
            st_code=evaluator.last_st_code,
            verification_plan=evaluator.last_plan,
            attempts=evaluator.attempts,
            final_message=fallback,
            model=model_info,
            state=control.state,
            requirement_spec=(requirements.spec.to_dict() if requirements.spec else None),
            clarification_options=control.clarification_options,
            model_final_message=self._final_message(run_result, "") or None,
        )


__all__ = ["PLCRepairAgent", "PLCToolCallingAgent"]
