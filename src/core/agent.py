"""Agent kernel.

Holds the LLMProvider + ToolRegistry + WorkflowRegistry + Conversation.
Drives the tool-calling loop: ask the LLM with the tool schema; if the
LLM requests tool calls, dispatch them and feed results back; repeat
until the LLM returns a plain text reply or the iteration cap is hit.

`turn()` yields events so the UI tool-call panel can render the call
sequence as it happens, not just the final answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import ChatMessage, LLMProvider
from ..tools.base import ToolRegistry
from ..workflows.base import WorkflowRegistry
from .conversation import Conversation
from .memory import MemoryStore, render_memory_context


@dataclass
class AgentEvent:
    """Emitted as the agent processes a turn."""

    # "assistant_delta" | "reasoning_delta" | "llm_response"
    # | "tool_call" | "tool_result" | "final"
    kind: str
    payload: dict[str, Any]


@dataclass
class Agent:
    llm: LLMProvider
    tools: ToolRegistry
    workflows: WorkflowRegistry
    conversation: Conversation = field(default_factory=Conversation)
    memory: MemoryStore | None = None
    max_tool_iterations: int = 8

    def turn(self, user_message: str) -> Iterator[AgentEvent]:
        """Process one user turn. Yields events as they happen."""
        self.conversation.add_user(user_message)
        tool_schema = self.tools.to_openai_schema()

        for _ in range(self.max_tool_iterations):
            response = None
            for stream_event in self.llm.stream_chat(
                self._messages_for_llm(),
                tools=tool_schema,
            ):
                if stream_event.reasoning_delta:
                    yield AgentEvent(
                        kind="reasoning_delta",
                        payload={"text": stream_event.reasoning_delta},
                    )
                if stream_event.delta:
                    yield AgentEvent(
                        kind="assistant_delta",
                        payload={"text": stream_event.delta},
                    )
                if stream_event.response is not None:
                    response = stream_event.response
            if response is None:
                response = self.llm.chat(self._messages_for_llm(), tools=tool_schema)
            yield AgentEvent(kind="llm_response", payload={"text": response.text})

            self.conversation.add_assistant(
                response.text,
                response.tool_calls,
                reasoning_content=response.reasoning_content,
            )

            if not response.tool_calls:
                yield AgentEvent(kind="final", payload={"text": response.text})
                return

            for call in response.tool_calls:
                yield AgentEvent(
                    kind="tool_call",
                    payload={"id": call.id, "name": call.name, "arguments": call.arguments},
                )
                result = self.tools.get(call.name).invoke(call.arguments)
                yield AgentEvent(
                    kind="tool_result",
                    payload={"id": call.id, "name": call.name, "result": result},
                )
                self.conversation.add_tool_result(
                    call_id=call.id,
                    name=call.name,
                    content=(
                        str(result.data) if result.success else f"ERROR: {result.error}"
                    ),
                )

        yield AgentEvent(
            kind="final",
            payload={"text": "Agent exceeded max tool iterations."},
        )

    def _messages_for_llm(self) -> list[ChatMessage]:
        """Conversation snapshot with current memory folded into context.

        Recomputed each LLM iteration so a `memory` tool call made earlier
        in the same turn is reflected immediately. The block is merged into
        the leading system message (rather than appended as a second system
        message — DeepSeek expects a single system turn) and is injected only
        into this copy; it never lands in `Conversation`, keeping the history
        the GUI renders clean and free of accumulating context blocks.
        """
        messages = self.conversation.snapshot()
        if self.memory is None:
            return messages
        block = render_memory_context(self.memory.list())
        if not block:
            return messages
        if messages and messages[0].role == "system":
            head = messages[0]
            messages[0] = ChatMessage(
                role="system",
                content=f"{head.content}\n\n{block}",
                name=head.name,
                tool_call_id=head.tool_call_id,
                tool_calls=head.tool_calls,
                reasoning_content=head.reasoning_content,
            )
        else:
            messages.insert(0, ChatMessage(role="system", content=block))
        return messages
