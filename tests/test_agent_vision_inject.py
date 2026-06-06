"""Agent injects a tool's page images as a multimodal user message.

When a tool returns `ToolResult.images` (doc_read renders PDF pages), the agent
must feed them to the vision brain as a `role=user` message with image parts —
placed *after* every tool result so the assistant(tool_calls) → tool → user
order stays valid.
"""

from __future__ import annotations

from typing import Any

from src.core.agent import Agent
from src.core.conversation import Conversation
from src.llm.base import ChatResponse, LLMProvider, ToolCall
from src.tools.base import Tool, ToolRegistry, ToolResult
from src.workflows.base import WorkflowRegistry


class _RenderTool(Tool):
    name = "doc_read"
    description = "render"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=True,
            data={"note": "《基础数学》第 1–2 页", "title": "基础数学"},
            images=("data:image/png;base64,p1", "data:image/png;base64,p2"),
        )


class _ScriptedLLM(LLMProvider):
    """Calls doc_read once, then answers from the (injected) images."""

    name = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                text="",
                tool_calls=[ToolCall(id="c1", name="doc_read", arguments={"path": "x.pdf"})],
            )
        return ChatResponse(text="毕业总学分：138")


def _agent() -> Agent:
    tools = ToolRegistry()
    tools.register(_RenderTool())
    conv = Conversation()
    conv.add_system("sys")
    return Agent(llm=_ScriptedLLM(), tools=tools, workflows=WorkflowRegistry(), conversation=conv)


def test_images_injected_as_user_message_after_tool_result() -> None:
    agent = _agent()
    finals = [e for e in agent.turn("毕业总学分是多少？") if e.kind == "final"]
    assert finals and finals[0].payload["text"] == "毕业总学分：138"

    roles = [m.role for m in agent.conversation.snapshot()]
    # system, user(typed), assistant(tool_calls), tool(result), user(images), assistant(final)
    assert roles == ["system", "user", "assistant", "tool", "user", "assistant"]

    injected = agent.conversation.snapshot()[4]
    assert injected.role == "user"
    assert isinstance(injected.content, list)
    types = [part["type"] for part in injected.content]
    assert types == ["image_url", "image_url", "text"]
    # the label carries the tool's note so the model knows what the pages are
    assert "基础数学" in injected.content[-1]["text"]


def test_no_injection_when_tool_returns_no_images() -> None:
    class _PlainTool(Tool):
        name = "clock"
        description = "c"
        parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

        def invoke(self, args: dict[str, Any]) -> ToolResult:
            return ToolResult(success=True, data="12:00")

    class _OneToolLLM(LLMProvider):
        name = "scripted2"

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, messages, tools=None) -> ChatResponse:
            self.calls += 1
            if self.calls == 1:
                return ChatResponse(
                    text="",
                    tool_calls=[ToolCall(id="c1", name="clock", arguments={})],
                )
            return ChatResponse(text="现在 12:00")

    tools = ToolRegistry()
    tools.register(_PlainTool())
    conv = Conversation()
    conv.add_system("sys")
    agent = Agent(llm=_OneToolLLM(), tools=tools, workflows=WorkflowRegistry(), conversation=conv)
    list(agent.turn("几点了？"))
    roles = [m.role for m in agent.conversation.snapshot()]
    # no extra user(images) message — ordinary tools don't trigger injection
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
