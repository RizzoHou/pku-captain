"""Conversation — owns the agent's chat-message history.

Lifted out of `Agent` so the kernel split (Conversation / ToolRegistry /
WorkflowRegistry / LLMProvider) lines up with the design doc, and so the
UI can render history without poking at agent internals.

The Conversation enforces the OpenAI/DeepSeek invariant that any `tool`
message must follow an `assistant` message whose `tool_calls` includes
the matching id. `add_tool_result` validates this at append time so a
bad sequence fails loud rather than at the API boundary.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from ..llm.base import ChatMessage, ToolCall


@dataclass
class Conversation:
    _messages: list[ChatMessage] = field(default_factory=list)

    def __iter__(self) -> Iterator[ChatMessage]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def snapshot(self) -> list[ChatMessage]:
        """Copy suitable for passing to an LLMProvider."""
        return list(self._messages)

    def add_system(self, content: str) -> None:
        self._messages.append(ChatMessage(role="system", content=content))

    def add_user(self, content: str) -> None:
        self._messages.append(ChatMessage(role="user", content=content))

    def add_assistant(
        self,
        content: str,
        tool_calls: Iterable[ToolCall] = (),
        reasoning_content: str | None = None,
    ) -> None:
        self._messages.append(
            ChatMessage(
                role="assistant",
                content=content,
                tool_calls=tuple(tool_calls),
                reasoning_content=reasoning_content,
            )
        )

    def add_tool_result(self, call_id: str, name: str, content: str) -> None:
        if not self._pending_call_id(call_id):
            raise ValueError(
                f"tool result for {call_id!r} has no matching assistant tool_call"
            )
        self._messages.append(
            ChatMessage(
                role="tool",
                name=name,
                tool_call_id=call_id,
                content=content,
            )
        )

    def reset(self) -> None:
        self._messages.clear()

    def load_messages(self, messages: Iterable[ChatMessage]) -> None:
        """Replace the history in place (keeps this object's identity).

        Used when restoring a saved session or resetting for a new chat.
        Replacing the list rather than swapping the `Conversation` instance
        keeps the reference `AgentWorker` already holds (`agent.conversation`)
        valid. The caller is responsible for any system-prompt seeding —
        this is a low-level primitive that `bootstrap` wraps.
        """
        self._messages = list(messages)

    def _pending_call_id(self, call_id: str) -> bool:
        for msg in reversed(self._messages):
            if msg.role == "assistant" and any(
                c.id == call_id for c in msg.tool_calls
            ):
                return True
            if msg.role == "tool" and msg.tool_call_id == call_id:
                return False
        return False
