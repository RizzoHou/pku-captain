"""Tool abstract base class and registry.

One of four parallel OOP hierarchies (Tool, Workflow, LLMProvider, Source).
Subclasses declare a JSON-schema parameter spec and implement `invoke`;
ToolRegistry holds instances and serializes them to OpenAI tool-call format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool invocation. Always populated, even on failure."""

    success: bool
    data: Any = None
    error: str | None = None
    # Optional image data URIs a tool produced for a vision-capable chat brain
    # to read directly (doc_read renders PDF pages here). The agent injects
    # these as a follow-up multimodal user message after the tool result; they
    # never ride the stringified tool-result `data`. Empty for ordinary tools.
    images: tuple[str, ...] = ()


class Tool(ABC):
    """Abstract tool callable by the agent.

    Subclasses set `name`, `description`, `parameters_schema` (a JSON
    schema describing the `invoke` argument dict) and implement `invoke`.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[dict[str, Any]]

    @abstractmethod
    def invoke(self, args: dict[str, Any]) -> ToolResult:
        """Run the tool with parsed arguments."""


@dataclass
class ToolRegistry:
    """Holds Tool instances by name; serializes them to the LLM."""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name if present (idempotent).

        Used to gate `doc_read` on the active chat brain: it registers only
        while a vision-capable brain (Kimi) is selected and is removed on a
        switch back to a text brain.
        """
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def find(self, name: str) -> Tool | None:
        """Return the tool by name, or None if it is not registered."""
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_openai_schema(self) -> list[dict[str, Any]]:
        """Serialize all tools for an OpenAI-style `tools=` parameter."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in self._tools.values()
        ]
