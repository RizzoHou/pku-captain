"""LLMProvider abstract base class and registry.

Subclasses adapt a specific provider (DeepSeek, Kimi, ...) to a uniform
chat interface returning text + optional tool-call requests. The Agent
treats all providers interchangeably.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    """A single chat-history entry in OpenAI format.

    `tool_calls` is only populated on assistant messages that requested
    tool invocations; per the OpenAI/DeepSeek spec, such an assistant
    message must be present in history before any subsequent `tool`-role
    reply, otherwise the API rejects the request.

    `reasoning_content` carries chain-of-thought output from reasoning
    models (e.g. DeepSeek with `effort=max`). DeepSeek requires it to be
    passed back to the API on the next turn for the model to continue
    coherently — providers that don't surface reasoning leave it `None`.
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning_content: str | None = None


@dataclass(frozen=True)
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None


@dataclass(frozen=True)
class ChatStreamEvent:
    """Incremental chat output.

    ``delta`` is the visible-answer token stream, suitable for live UI
    rendering. ``reasoning_delta`` is the chain-of-thought token stream from
    reasoning models (DeepSeek thinking mode) — emitted before the answer and
    rendered separately so a long CoT doesn't flood the answer view.
    ``response`` is set once at the end and carries tool calls plus the
    complete assistant message (text + accumulated ``reasoning_content``).
    """

    delta: str = ""
    reasoning_delta: str = ""
    response: ChatResponse | None = None


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

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatStreamEvent]:
        """Stream chat output when supported; default falls back to one call."""
        response = self.chat(messages, tools=tools)
        yield ChatStreamEvent(response=response)


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
