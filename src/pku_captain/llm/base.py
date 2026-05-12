"""LLMProvider abstract base class and registry.

Subclasses adapt a specific provider (DeepSeek, Kimi, ...) to a uniform
chat interface returning text + optional tool-call requests. The Agent
treats all providers interchangeably.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal


@dataclass(frozen=True)
class ChatMessage:
    """A single chat-history entry in OpenAI format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    """Abstract chat-LLM provider."""

    name: ClassVar[str]

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """Call the underlying LLM; return text + any tool-call requests."""


@dataclass
class LLMProviderRegistry:
    _providers: dict[str, LLMProvider] = field(default_factory=dict)

    def register(self, provider: LLMProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider:
        return self._providers[name]

    def all(self) -> list[LLMProvider]:
        return list(self._providers.values())
