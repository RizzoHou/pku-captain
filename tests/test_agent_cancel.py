"""Cooperative turn cancellation (`Agent.turn(..., cancelled=...)`).

A turn must stop at the next safe boundary when the predicate flips, leave
`Conversation` in a valid state (clean user→assistant alternation, every
tool_call answered), and let a *following* turn run without error. The offline
suite can't catch the live thinking-mode reasoning-replay 400 (ScriptedLLM
doesn't exercise the wire format) — that needs a real DeepSeek round-trip — but
it does guard the structural invariants the next turn depends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from src.core.agent import Agent
from src.core.conversation import Conversation
from src.llm.base import (
    ChatMessage,
    ChatResponse,
    ChatStreamEvent,
    LLMProvider,
    ToolCall,
)
from src.tools.base import Tool, ToolRegistry, ToolResult
from src.workflows.base import WorkflowRegistry

_NOTE = "（已被用户中断）"


class CountingTool(Tool):
    name = "counting"
    description = "counting"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(success=True, data={"ok": True})


class StreamArmingLLM(LLMProvider):
    """Streams deltas and flips a shared cancel flag after the first one.

    The generator arms the flag *between* yielding the first and second delta,
    so the agent's per-token cancel check trips mid-stream deterministically —
    no fragile call-count threshold.
    """

    name = "stream-arming"

    def __init__(self, flag: list[bool]) -> None:
        self._flag = flag
        self.chat_calls = 0

    def chat(self, messages: list[ChatMessage], tools: Any = None) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(text="Hello world")

    def stream_chat(
        self, messages: list[ChatMessage], tools: Any = None
    ) -> Iterator[ChatStreamEvent]:
        yield ChatStreamEvent(delta="Hello")
        self._flag[0] = True  # arm: next per-iteration check breaks the loop
        yield ChatStreamEvent(delta=" world")
        yield ChatStreamEvent(response=ChatResponse(text="Hello world"))


class ToolThenAnswerLLM(LLMProvider):
    """First response asks for two tool calls; later responses are plain text.

    `stream_chat` arms the flag only as the stream *ends* (after the response is
    yielded), so the cancel trips at the tool-dispatch boundary, not mid-stream.
    """

    name = "tool-then-answer"

    def __init__(self, flag: list[bool], arm_on_first: bool) -> None:
        self._flag = flag
        self._arm_on_first = arm_on_first
        self._turn = 0

    def chat(self, messages: list[ChatMessage], tools: Any = None) -> ChatResponse:
        return self._next_response()

    def _next_response(self) -> ChatResponse:
        self._turn += 1
        if self._turn == 1:
            return ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(id="c1", name="counting", arguments={}),
                    ToolCall(id="c2", name="counting", arguments={}),
                ],
            )
        return ChatResponse(text="done")

    def stream_chat(
        self, messages: list[ChatMessage], tools: Any = None
    ) -> Iterator[ChatStreamEvent]:
        first = self._turn == 0
        yield ChatStreamEvent(response=self._next_response())
        if first and self._arm_on_first:
            self._flag[0] = True


def _agent(llm: LLMProvider, *, max_tool_iterations: int = 8) -> tuple[Agent, CountingTool]:
    tools = ToolRegistry()
    tool = CountingTool()
    tools.register(tool)
    conversation = Conversation()
    conversation.add_system("BASE")
    agent = Agent(
        llm=llm,
        tools=tools,
        workflows=WorkflowRegistry(),
        conversation=conversation,
        max_tool_iterations=max_tool_iterations,
    )
    return agent, tool


def _assert_conversation_valid(conversation: Conversation) -> None:
    messages = conversation.snapshot()
    # No two consecutive user turns — the cancel path must keep alternation.
    roles = [m.role for m in messages]
    for prev, cur in zip(roles, roles[1:], strict=False):
        assert not (prev == "user" and cur == "user"), roles
    # Every assistant tool_call id is answered by a following tool message.
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    for m in messages:
        if m.role == "assistant":
            for call in m.tool_calls:
                assert call.id in answered, f"{call.id} unanswered: {roles}"
    # Conversation ends with an assistant turn (ready for the next user message).
    assert messages[-1].role == "assistant", roles


def test_cancel_before_stream_emits_only_final() -> None:
    flag = [True]  # already cancelled when the turn starts
    llm = StreamArmingLLM(flag)
    agent, tool = _agent(llm)

    events = list(agent.turn("hi", cancelled=lambda: flag[0]))

    assert [e.kind for e in events] == ["final"]
    assert events[-1].payload["text"] == _NOTE
    assert llm.chat_calls == 0  # never reached the model
    assert tool.calls == []
    _assert_conversation_valid(agent.conversation)


def test_cancel_mid_stream_keeps_partial_text() -> None:
    flag = [False]
    llm = StreamArmingLLM(flag)
    agent, _tool = _agent(llm)

    events = list(agent.turn("hi", cancelled=lambda: flag[0]))

    kinds = [e.kind for e in events]
    assert kinds == ["assistant_delta", "final"], kinds
    assert events[0].payload["text"] == "Hello"
    final = events[-1].payload["text"]
    assert final == f"Hello\n\n{_NOTE}"
    # The synthetic assistant message and the final text match (reload parity).
    assert agent.conversation.snapshot()[-1].content == final
    _assert_conversation_valid(agent.conversation)


def test_cancel_in_tool_loop_fills_pending_results() -> None:
    flag = [False]
    llm = ToolThenAnswerLLM(flag, arm_on_first=True)
    agent, tool = _agent(llm)

    events = list(agent.turn("use tools", cancelled=lambda: flag[0]))

    # Cancel tripped before the first dispatch: no tool ran, no tool_call/result
    # events surfaced, and the turn still closed with a final note.
    assert tool.calls == []
    assert "tool_call" not in [e.kind for e in events]
    assert events[-1].kind == "final"
    assert events[-1].payload["text"] == _NOTE
    # Both requested calls are answered (cancelled), so history stays valid.
    tool_msgs = [m for m in agent.conversation if m.role == "tool"]
    assert {m.tool_call_id for m in tool_msgs} == {"c1", "c2"}
    assert all(_NOTE in m.content for m in tool_msgs)
    _assert_conversation_valid(agent.conversation)


def test_turn_after_cancel_runs_clean() -> None:
    flag = [False]
    llm = ToolThenAnswerLLM(flag, arm_on_first=True)
    agent, _tool = _agent(llm)

    list(agent.turn("use tools", cancelled=lambda: flag[0]))  # cancelled turn
    flag[0] = False  # user did not cancel the follow-up
    events = list(agent.turn("继续"))

    assert events[-1].kind == "final"
    assert events[-1].payload["text"] == "done"
    _assert_conversation_valid(agent.conversation)


def test_no_cancel_predicate_is_unchanged() -> None:
    flag = [False]
    llm = ToolThenAnswerLLM(flag, arm_on_first=False)
    agent, tool = _agent(llm)

    events = list(agent.turn("use tools"))  # no `cancelled` arg

    # Both tools dispatch, the second iteration answers — normal flow intact.
    assert len(tool.calls) == 2
    assert events[-1].kind == "final"
    assert events[-1].payload["text"] == "done"
    _assert_conversation_valid(agent.conversation)
