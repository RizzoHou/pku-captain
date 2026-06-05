"""Agent guard for context-length API errors (and the reasoning round-trip)."""

from __future__ import annotations

from typing import Any

import pytest

from src.core.agent import Agent
from src.core.conversation import Conversation
from src.llm.base import ChatMessage, ChatResponse, LLMProvider, ToolCall
from src.tools.base import Tool, ToolRegistry, ToolResult
from src.workflows.base import WorkflowRegistry


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(
        self,
        responses: list[ChatResponse] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._error = error
        self.calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        if self._error is not None:
            raise self._error
        if self._responses:
            return self._responses.pop(0)
        return ChatResponse(text="ok")


class CountingTool(Tool):
    name = "counting"
    description = "counting"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(success=True, data={"ok": True})


def _agent(llm: LLMProvider, *, max_tool_iterations: int = 8):
    tools = ToolRegistry()
    tool = CountingTool()
    tools.register(tool)
    conversation = Conversation()
    conversation.add_system("BASE")
    return (
        Agent(
            llm=llm,
            tools=tools,
            workflows=WorkflowRegistry(),
            conversation=conversation,
            max_tool_iterations=max_tool_iterations,
        ),
        tool,
    )


def test_reasoning_content_is_preserved_in_llm_messages() -> None:
    llm = ScriptedLLM([ChatResponse(text="ok")])
    agent, _tool = _agent(llm)
    agent.conversation.add_assistant("earlier answer", reasoning_content="earlier thought")

    list(agent.turn("CURRENT QUESTION"))

    sent = llm.calls[0]
    assert sent[0].role == "system"
    assert any(message.content == "CURRENT QUESTION" for message in sent)
    assert any(
        message.role == "assistant" and message.reasoning_content == "earlier thought"
        for message in sent
    )


def test_context_length_api_error_becomes_user_facing_final() -> None:
    llm = ScriptedLLM(error=RuntimeError("exceeding maximum context length"))
    agent, _tool = _agent(llm)

    events = list(agent.turn("hi"))

    assert events[-1].kind == "final"
    assert "上下文长度" in events[-1].payload["text"]


def test_quota_error_is_not_treated_as_context_length() -> None:
    # A bare "exceed" marker would mislabel a quota/rate-limit error as an
    # over-long history; such errors must propagate, not become a final.
    llm = ScriptedLLM(error=RuntimeError("Error code: 429 - rate limit exceeded"))
    agent, _tool = _agent(llm)

    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        list(agent.turn("hi"))


def test_max_tool_iterations_returns_chinese_final_message() -> None:
    llm = ScriptedLLM(
        [ChatResponse(text="", tool_calls=[ToolCall(id="c1", name="counting", arguments={})])]
    )
    agent, tool = _agent(llm, max_tool_iterations=1)

    events = list(agent.turn("use tool"))

    assert tool.calls == [{}]
    assert events[-1].kind == "final"
    assert "工具调用已达到上限" in events[-1].payload["text"]
    assert "Agent exceeded max tool iterations" not in events[-1].payload["text"]
