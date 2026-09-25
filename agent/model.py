"""Real LLM configuration for the M5 agent.

M5 intentionally supports one provider path first: smolagents' OpenAIModel
against an OpenAI-compatible chat-completions endpoint.  The API key must be
provided by the environment; this module never supplies a mock model.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Literal

from ._smolagents import ChatMessage, MessageRole, OpenAIModel, Tool


class ModelConfigurationError(RuntimeError):
    """Raised when a real model cannot be configured safely."""


class ModelPreflightError(RuntimeError):
    """The endpoint responded but cannot perform this Agent's tool protocol."""

    def __init__(self, message: str, kind: Literal["model_tool_unsupported", "model_output_invalid"]):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_id: str
    api_key: str
    api_base: str | None = None
    timeout: int = 120
    max_tokens: int = 8192
    temperature: float = 0.0

    def public_dict(self) -> dict[str, str]:
        result = {"provider": self.provider, "model_id": self.model_id}
        if self.api_base:
            result["api_base"] = self.api_base
        return result


def _positive_int(raw: str | None, name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ModelConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ModelConfigurationError(f"{name} must be positive")
    return value


def _temperature(raw: str | None) -> float:
    if raw is None or not raw.strip():
        return 0.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ModelConfigurationError("PLC_AGENT_TEMPERATURE must be a number") from exc
    if not 0 <= value <= 2:
        raise ModelConfigurationError("PLC_AGENT_TEMPERATURE must be between 0 and 2")
    return value


def load_model_config(
    *,
    provider: str | None = None,
    model_id: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ModelConfig:
    """Load a real model configuration without exposing secrets in results."""

    selected_provider = (provider or os.getenv("PLC_AGENT_MODEL_PROVIDER", "openai")).strip().lower()
    selected_model = (model_id or os.getenv("PLC_AGENT_MODEL_ID", "")).strip()
    selected_key = api_key or os.getenv("PLC_AGENT_API_KEY", "")
    selected_base = api_base or os.getenv("PLC_AGENT_API_BASE")
    if selected_provider != "openai":
        raise ModelConfigurationError(
            f"unsupported M5 model provider '{selected_provider}'; supported provider is 'openai'"
        )
    if not selected_model:
        raise ModelConfigurationError("PLC_AGENT_MODEL_ID is required")
    if not selected_key:
        raise ModelConfigurationError("PLC_AGENT_API_KEY is required")
    return ModelConfig(
        provider=selected_provider,
        model_id=selected_model,
        api_key=selected_key,
        api_base=selected_base.strip() if selected_base and selected_base.strip() else None,
        timeout=_positive_int(os.getenv("PLC_AGENT_MODEL_TIMEOUT"), "PLC_AGENT_MODEL_TIMEOUT", 120),
        max_tokens=_positive_int(os.getenv("PLC_AGENT_MAX_TOKENS"), "PLC_AGENT_MAX_TOKENS", 8192),
        temperature=_temperature(os.getenv("PLC_AGENT_TEMPERATURE")),
    )


def build_model(config: ModelConfig | None = None, **overrides: Any):
    """Build smolagents' real OpenAI-compatible model."""

    selected = config or load_model_config(**overrides)
    model_kwargs: dict[str, Any] = {
        "model_id": selected.model_id,
        "api_base": selected.api_base,
        "api_key": selected.api_key,
        "timeout": selected.timeout,
        "max_tokens": selected.max_tokens,
        "temperature": selected.temperature,
        "tool_choice": "auto",
    }
    try:
        return OpenAIModel(**model_kwargs)
    except ModuleNotFoundError as exc:
        raise ModelConfigurationError(
            "OpenAIModel requires the smolagents openai extra; install the openai package"
        ) from exc


def preflight_model(model: OpenAIModel, tools: list[Tool]) -> None:
    """Exercise the configured endpoint with the actual Agent tool schemas.

    A successful completion establishes that credentials, model id, and the
    complete tool-schema payload are accepted. A returned tool call also proves
    the model can speak the protocol; it is never executed by this probe.
    """

    reply = model.generate(
        [
            ChatMessage(
                role=MessageRole.USER,
                content=(
                    "Tool capability check only. Call final_answer with answer "
                    "'PLC_PREFLIGHT_OK'. Do not perform any PLC work."
                ),
            )
        ],
        tools_to_call_from=tools,
    )
    calls = reply.tool_calls or []
    if not calls:
        raise ModelPreflightError(
            "Model did not return a tool call in the tool-capability check; "
            "select a tool-calling model or endpoint.",
            "model_tool_unsupported",
        )
    if len(calls) != 1:
        raise ModelPreflightError(
            "Model returned parallel tool calls, but this Agent requires one action at a time.",
            "model_output_invalid",
        )
    tool_names = {tool.name for tool in tools}
    for call in calls:
        function = getattr(call, "function", None)
        if function is None or getattr(function, "name", None) not in tool_names:
            raise ModelPreflightError(
                "Model returned a tool name outside the supplied schema.",
                "model_output_invalid",
            )
        arguments = getattr(function, "arguments", None)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (TypeError, ValueError) as exc:
            raise ModelPreflightError(
                "Model returned malformed tool-call arguments.",
                "model_output_invalid",
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelPreflightError(
                "Model returned non-object tool-call arguments.",
                "model_output_invalid",
            )
        if function.name != "final_answer" or not isinstance(parsed.get("answer"), str):
            raise ModelPreflightError(
                "Model did not follow the harmless final_answer tool probe.",
                "model_output_invalid",
            )

