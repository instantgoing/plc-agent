"""PLC-specialized smolagents agent and the public M5 repair-loop entrypoint."""

from __future__ import annotations

from typing import Any

from ._smolagents import AgentExecutionError, ToolCallingAgent
from .contracts import FailureKind, M5Request, M5Result
from .model import ModelConfig, ModelConfigurationError, build_model, load_model_config
from .prompts import FINAL_ANSWER_INSTRUCTIONS, PLC_SYSTEM_INSTRUCTIONS
from .tools import CandidateEvaluator, EvaluateCandidateTool


def _final_answer_is_allowed(answer: Any, memory: Any, *, agent: "PLCToolCallingAgent") -> bool:
    del answer, memory
    return bool(agent.state.get("plc_accepted") or agent.state.get("plc_fatal"))


class PLCToolCallingAgent(ToolCallingAgent):
    """A ToolCallingAgent constrained to one serial PLC candidate evaluator."""

    def __init__(self, *, evaluator: CandidateEvaluator, model: Any, **kwargs: Any):
        self.evaluator = evaluator
        instructions = kwargs.pop("instructions", "")
        combined_instructions = "\n\n".join(
            part for part in (PLC_SYSTEM_INSTRUCTIONS, instructions, FINAL_ANSWER_INSTRUCTIONS) if part
        )
        super().__init__(
            tools=[EvaluateCandidateTool(evaluator)],
            model=model,
            instructions=combined_instructions,
            add_base_tools=False,
            planning_interval=None,
            stream_outputs=False,
            max_tool_threads=1,
            max_steps=evaluator.max_attempts + 1,
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

        if (self.evaluator.fatal or self.evaluator.accepted) and tool_name == "evaluate_candidate":
            return self.evaluator.last_result
        result = super().execute_tool_call(tool_name, arguments)
        if tool_name == "evaluate_candidate" and isinstance(result, dict):
            self.state["plc_last_evaluation"] = result
            self.state["plc_accepted"] = bool(result.get("accepted"))
            self.state["plc_fatal"] = not bool(result.get("retryable", True))
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
            "candidate_compile_failed",
            "runtime_start_failed",
            "behavior_verification_failed",
            "unverifiable_requirement",
            "attempt_limit_reached",
            "runtime_busy",
            "tool_unavailable",
        }
        return candidate if candidate in known else None

    def run(self, request: M5Request | str, *, max_attempts: int | None = None) -> M5Result:
        if isinstance(request, str):
            request = M5Request(task=request, max_attempts=max_attempts or 3)
        elif max_attempts is not None:
            request = M5Request(
                task=request.task,
                max_attempts=max_attempts,
                source_filename=request.source_filename,
            )
        validation_error = request.validate()
        if validation_error:
            return M5Result(
                success=False,
                failure_kind="invalid_request",
                st_code=None,
                verification_plan=None,
                attempts=[],
                final_message=validation_error,
                model=None,
            )

        try:
            model, model_info = self._build_model()
        except ModelConfigurationError as exc:
            return M5Result(
                success=False,
                failure_kind="model_unavailable",
                st_code=None,
                verification_plan=None,
                attempts=[],
                final_message=str(exc),
                model=None,
            )

        evaluator = CandidateEvaluator(
            max_attempts=request.max_attempts,
            source_filename=request.source_filename,
        )
        agent = PLCToolCallingAgent(evaluator=evaluator, model=model)
        try:
            agent.run(request.task, return_full_result=True)
        except Exception as exc:
            failure_kind: FailureKind = "model_output_invalid"
            if not evaluator.attempts:
                failure_kind = "model_unavailable"
            if evaluator.last_result and evaluator.last_result.get("feedback"):
                failure_kind = self._failure_from_feedback(evaluator.last_result["feedback"]) or failure_kind
            return M5Result(
                success=False,
                failure_kind=failure_kind,
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message=f"M5 agent execution failed: {type(exc).__name__}: {exc}",
                model=model_info,
            )

        if evaluator.accepted:
            return M5Result(
                success=True,
                failure_kind=None,
                st_code=evaluator.last_st_code,
                verification_plan=evaluator.last_plan,
                attempts=evaluator.attempts,
                final_message="Real PLC behavior verification passed.",
                model=model_info,
            )

        feedback = evaluator.last_result.get("feedback") if evaluator.last_result else None
        failure_kind = self._failure_from_feedback(feedback) or "attempt_limit_reached"
        return M5Result(
            success=False,
            failure_kind=failure_kind,
            st_code=evaluator.last_st_code,
            verification_plan=evaluator.last_plan,
            attempts=evaluator.attempts,
            final_message=(
                "The bounded repair budget ended without real behavior verification."
                if failure_kind == "attempt_limit_reached"
                else "The candidate was not accepted by the real PLC evaluation pipeline."
            ),
            model=model_info,
        )


__all__ = ["PLCRepairAgent", "PLCToolCallingAgent"]
