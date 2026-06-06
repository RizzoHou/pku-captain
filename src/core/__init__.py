"""Core package — agent kernel plus the GUI-facing composition root.

`build_agent` / `build_source_registry` live in `bootstrap`, which imports
the full tool / LLM / source set. Several tool modules in turn import
`src.core.memory`, so importing `bootstrap` eagerly here would create a
`core` <-> `tools` import cycle: it breaks whenever `src.tools` is imported
before `src.core` (the cycle only happens to resolve under the import order
the CLI / `__main__` entry points use). The two factories are therefore
exposed lazily via module ``__getattr__`` (PEP 562) — the heavy import runs
on first access, by which point both packages are fully initialised.
`from src.core import build_agent` keeps working unchanged.

`Agent` / `AgentEvent` / `Conversation` stay eager: they only pull leaf
`.base` modules and so never re-enter the cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .agent import Agent, AgentEvent
from .conversation import Conversation
from .memory_learn import MemoryLearnResult, MemoryLearnService
from .vision_router import VisionRouter

if TYPE_CHECKING:
    from .bootstrap import (
        DEFAULT_CHAT_MODEL,
        apply_chat_model,
        available_chat_models,
        build_agent,
        build_chat_llm,
        build_dashboard_cache,
        build_doc_reader,
        build_session_store,
        build_session_titler,
        build_source_registry,
        reset_conversation,
        restore_conversation,
    )

__all__ = [
    "DEFAULT_CHAT_MODEL",
    "Agent",
    "AgentEvent",
    "Conversation",
    "MemoryLearnResult",
    "MemoryLearnService",
    "VisionRouter",
    "apply_chat_model",
    "available_chat_models",
    "build_agent",
    "build_chat_llm",
    "build_dashboard_cache",
    "build_doc_reader",
    "build_session_store",
    "build_session_titler",
    "build_source_registry",
    "reset_conversation",
    "restore_conversation",
]

_LAZY = frozenset(
    {
        "DEFAULT_CHAT_MODEL",
        "apply_chat_model",
        "available_chat_models",
        "build_agent",
        "build_chat_llm",
        "build_dashboard_cache",
        "build_doc_reader",
        "build_session_store",
        "build_session_titler",
        "build_source_registry",
        "reset_conversation",
        "restore_conversation",
    }
)


def __getattr__(name: str) -> Any:
    """Resolve the bootstrap factories on first access (see module docstring)."""
    if name in _LAZY:
        from . import bootstrap

        return getattr(bootstrap, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
