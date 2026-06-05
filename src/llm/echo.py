"""EchoLLMProvider — reference LLMProvider subclass.

Offline provider that echoes the most recent user message back. Lets the
agent loop, UI, and tests run end-to-end without an API key or network.
Real providers (DeepSeekProvider, KimiProvider) follow the same shape.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import ChatMessage, ChatResponse, LLMProvider


class EchoLLMProvider(LLMProvider):
    name: ClassVar[str] = "echo"
    # Mirror the real app's headline model so the offline context meter shows
    # the same 1M window users see online.
    context_window: ClassVar[int] = 1_000_000

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        return ChatResponse(text=f"echo: {last_user}")
