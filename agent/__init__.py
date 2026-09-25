"""Codex-backed PLC Agent service; PLC tools remain independently callable."""

from importlib import import_module

from .codex_client import CodexClient, CodexInfrastructureError
from .codex_session import CodexPLCSession, PLCTaskResult

__all__ = ["CodexClient", "CodexInfrastructureError", "CodexPLCSession", "PLCTaskResult"]

# Old test modules still exercise the previous Agent while the real Codex
# acceptance gate is pending. Keep imports lazy so the CLI never loads it.
_LEGACY = {
    "AgentControlState": "contracts", "AttemptRecord": "contracts",
    "M5Request": "contracts", "M5Result": "contracts",
    "RequirementSpec": "contracts", "RunState": "contracts",
    "ModelConfigurationError": "model", "build_model": "model",
    "load_model_config": "model", "PLCRepairAgent": "plc_agent",
    "PLCToolCallingAgent": "plc_agent", "PLCEvent": "events",
    "SessionMetrics": "metrics", "PLCSession": "session",
}


def __getattr__(name: str):
    module_name = _LEGACY.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(f".{module_name}", __name__), name)
