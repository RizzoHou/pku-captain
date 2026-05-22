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

if TYPE_CHECKING:
    from .bootstrap import build_agent, build_source_registry

__all__ = [
    "Agent",
    "AgentEvent",
    "Conversation",
    "build_agent",
    "build_source_registry",
]

_LAZY = frozenset({"build_agent", "build_source_registry"})


def __getattr__(name: str) -> Any:
    """Resolve the bootstrap factories on first access (see module docstring)."""
    if name in _LAZY:
        from . import bootstrap

        return getattr(bootstrap, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
