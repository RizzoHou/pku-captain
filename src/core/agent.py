"""Agent kernel.

Holds the LLMProvider + ToolRegistry + WorkflowRegistry. Drives the
tool-calling loop: ask the LLM with the tool schema; if the LLM requests
tool calls, dispatch them and feed results back; repeat until the LLM
returns a plain text reply or the iteration cap is hit.

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


@dataclass
class AgentEvent:
    """Emitted as the agent processes a turn."""

    kind: str  # "llm_response" | "tool_call" | "tool_result" | "final"
    payload: dict[str, Any]


@dataclass
class Agent:
    llm: LLMProvider
    tools: ToolRegistry
    workflows: WorkflowRegistry
    history: list[ChatMessage] = field(default_factory=list)
    max_tool_iterations: int = 8

    def turn(self, user_message: str) -> Iterator[AgentEvent]:
        """Process one user turn. Yields events as they happen."""
        self.history.append(ChatMessage(role="user", content=user_message))
        tool_schema = self.tools.to_openai_schema()

        for _ in range(self.max_tool_iterations):
            response = self.llm.chat(self.history, tools=tool_schema)
            yield AgentEvent(kind="llm_response", payload={"text": response.text})

            if not response.tool_calls:
                self.history.append(
                    ChatMessage(role="assistant", content=response.text)
                )
                yield AgentEvent(kind="final", payload={"text": response.text})
                return

            self.history.append(
                ChatMessage(role="assistant", content=response.text)
            )
            for call in response.tool_calls:
                yield AgentEvent(
                    kind="tool_call",
                    payload={"name": call.name, "arguments": call.arguments},
                )
                result = self.tools.get(call.name).invoke(call.arguments)
                yield AgentEvent(
                    kind="tool_result",
                    payload={"name": call.name, "result": result},
                )
                self.history.append(
                    ChatMessage(
                        role="tool",
                        name=call.name,
                        tool_call_id=call.id,
                        content=(
                            str(result.data)
                            if result.success
                            else f"ERROR: {result.error}"
                        ),
                    )
                )

        yield AgentEvent(
            kind="final",
            payload={"text": "Agent exceeded max tool iterations."},
        )
