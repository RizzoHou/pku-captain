"""LLMProvider abstract base class and registry.

Subclasses adapt a specific provider (DeepSeek, Kimi, ...) to a uniform
chat interface returning text + optional tool-call requests. The Agent
treats all providers interchangeably.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
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


def text_part(text: str) -> dict[str, Any]:
    """A text content part for a multimodal (vision) message."""
    return {"type": "text", "text": text}


def image_part(url: str) -> dict[str, Any]:
    """An image content part for a multimodal (vision) message.

    `url` is either a remote URL or a `data:image/...;base64,...` URI. This is
    the OpenAI vision format Kimi (and other multimodal providers) accept.
    """
    return {"type": "image_url", "image_url": {"url": url}}


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for one LLM call, as reported by the provider.

    OpenAI-compatible APIs (DeepSeek included) return this in the response's
    ``usage`` object. ``total_tokens`` (prompt + completion) of the most recent
    call is the best gauge of how much the conversation now occupies — it is
    roughly what the *next* request's prompt will cost.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None
    usage: TokenUsage | None = None


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
    # Maximum tokens the model accepts in one request (prompt + completion).
    # Drives the GUI's context-usage meter; subclasses override with the real
    # window of their default model. Conservative generic default. A subclass
    # may also set an *instance* attribute of the same name (from a
    # user-configured window) — it shadows this ClassVar for that instance.
    context_window: ClassVar[int] = 128_000

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


def estimate_tokens(messages: Iterable[ChatMessage]) -> int:
    """Rough token count for a message list, when no API usage is available.

    A heuristic gauge for the context meter offline (Echo) or for a freshly
    restored session before its next turn — not an exact tokenizer. It counts
    content, replayed ``reasoning_content``, and serialized tool-call arguments,
    plus a small per-message overhead. It will under-report versus a live
    ``prompt_tokens`` (which also includes the tools schema), so the GUI marks
    estimates as approximate. ASCII text is ~4 chars/token; wide (CJK) text is
    denser at ~0.6 tokens/char.
    """
    total = 0.0
    for m in messages:
        total += _content_tokens(m.content)
        if m.reasoning_content:
            total += _text_tokens(m.reasoning_content)
        for call in m.tool_calls:
            total += _text_tokens(call.name)
            total += _text_tokens(json.dumps(call.arguments, ensure_ascii=False))
        total += 4  # role / formatting overhead per message
    return round(total)


def _content_tokens(content: Any) -> float:
    """Token estimate for a message's `content` — a string or a multimodal
    list of `{type: text|image_url, ...}` parts (doc_read page images). Each
    image is charged a flat ~1600 tokens (observed ~2.5k for a 150-DPI page,
    kept conservative so the meter never wildly over-reports)."""
    if isinstance(content, str):
        return _text_tokens(content)
    if isinstance(content, list):
        total = 0.0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += _text_tokens(part.get("text") or "")
            elif part.get("type") == "image_url":
                total += 1600
        return total
    return 0.0


def _text_tokens(text: str) -> float:
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return ascii_count / 4 + (len(text) - ascii_count) * 0.6


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
