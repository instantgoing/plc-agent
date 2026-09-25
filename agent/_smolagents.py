"""Import the repository-local smolagents source reproducibly.

The project intentionally vendors smolagents under ``smolagents/src`` rather
than depending on an unrelated global installation. The repository-local
source root is placed first so the top-level source directory cannot shadow
the actual package as a namespace package.
"""

from __future__ import annotations

import sys
from pathlib import Path


_source_root = Path(__file__).resolve().parents[1] / "smolagents" / "src"
if _source_root.is_dir():
    # The repository root also contains a directory named ``smolagents``.
    # Put its src root first so that directory cannot become a namespace
    # package and shadow the actual vendored package.
    source_text = str(_source_root)
    if source_text in sys.path:
        sys.path.remove(source_text)
    sys.path.insert(0, source_text)

from smolagents import (  # type: ignore[no-redef]
    AgentExecutionError,
    ChatMessage,
    Tool,
    ToolCallingAgent,
)
from smolagents import OpenAIModel  # type: ignore[no-redef]
from smolagents.models import (  # type: ignore[no-redef]
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
    Model,
)
from smolagents.utils import AgentParsingError, AgentToolCallError  # type: ignore[no-redef]


__all__ = [
    "AgentExecutionError",
    "AgentParsingError",
    "AgentToolCallError",
    "ChatMessage",
    "ChatMessageToolCall",
    "ChatMessageToolCallFunction",
    "MessageRole",
    "Model",
    "OpenAIModel",
    "Tool",
    "ToolCallingAgent",
]
