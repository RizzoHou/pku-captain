"""Context-usage plumbing: token estimation, DeepSeek usage parsing, and the
``context_usage`` event the GUI meter renders.

The bar is the proactive complement to ``Agent._is_context_length_error``: it
shows how much of the model's window is occupied before the window is blown.
"""

from __future__ import annotations

from typing import Any

from src.core.agent import Agent
from src.core.conversation import Conversation
from src.llm.base import (
    ChatMessage,
    ChatResponse,
    LLMProvider,
    TokenUsage,
    ToolCall,
    estimate_tokens,
)
from src.llm.deepseek import DeepSeekProvider, _parse_usage
from src.tools.base import ToolRegistry
from src.workflows.base import WorkflowRegistry


# --- estimate_tokens -------------------------------------------------------
def test_estimate_tokens_grows_with_content() -> None:
    short = [ChatMessage(role="user", content="hi")]
    long = [ChatMessage(role="user", content="hello world " * 50)]
    assert estimate_tokens(short) < estimate_tokens(long)


def test_estimate_tokens_counts_cjk_heavier_than_ascii() -> None:
    # Same character count; CJK should weigh more per char than ASCII.
    ascii_msg = [ChatMessage(role="user", content="a" * 100)]
    cjk_msg = [ChatMessage(role="user", content="中" * 100)]
    assert estimate_tokens(cjk_msg) > estimate_tokens(ascii_msg)


def test_estimate_tokens_includes_reasoning_and_tool_calls() -> None:
    base = [ChatMessage(role="assistant", content="answer")]
    with_extra = [
        ChatMessage(
            role="assistant",
            content="answer",
            reasoning_content="a long chain of thought " * 10,
            tool_calls=(ToolCall(id="c1", name="clock", arguments={"tz": "UTC"}),),
        )
    ]
    assert estimate_tokens(with_extra) > estimate_tokens(base)


def test_estimate_tokens_empty_is_zero() -> None:
    assert estimate_tokens([]) == 0


# --- DeepSeek usage parsing ------------------------------------------------
def test_parse_usage_none() -> None:
    assert _parse_usage(None) is None
    assert _parse_usage({}) is None


def test_parse_usage_full() -> None:
    usage = _parse_usage(
        {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    )
    assert usage == TokenUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150)


def test_parse_usage_derives_total_when_missing() -> None:
    usage = _parse_usage({"prompt_tokens": 120, "completion_tokens": 30})
    assert usage is not None
    assert usage.total_tokens == 150


def test_deepseek_window_is_one_million() -> None:
    assert DeepSeekProvider.context_window == 1_000_000


def test_stream_body_requests_usage_but_chat_body_does_not() -> None:
    provider = DeepSeekProvider(api_key="x")
    stream_body = provider._build_body([], None, stream=True)
    chat_body = provider._build_body([], None, stream=False)
    assert stream_body["stream_options"] == {"include_usage": True}
    assert "stream_options" not in chat_body
    # Thinking path stays byte-identical on the token-accounting-free fields.
    assert chat_body["reasoning_effort"] == "max"


# --- Agent context_usage event --------------------------------------------
class _UsageLLM(LLMProvider):
    name = "usagetest"
    context_window = 1_000_000

    def __init__(self, response: ChatResponse) -> None:
        self._response = response

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        return self._response


def _agent(llm: LLMProvider) -> Agent:
    conversation = Conversation()
    conversation.add_system("BASE")
    return Agent(
        llm=llm,
        tools=ToolRegistry(),
        workflows=WorkflowRegistry(),
        conversation=conversation,
    )


def test_turn_emits_real_usage_when_provided() -> None:
    usage = TokenUsage(prompt_tokens=900, completion_tokens=100, total_tokens=1000)
    agent = _agent(_UsageLLM(ChatResponse(text="hello", usage=usage)))

    events = [e for e in agent.turn("hi") if e.kind == "context_usage"]

    assert len(events) == 1
    payload = events[0].payload
    assert payload == {"used": 1000, "window": 1_000_000, "estimated": False}


def test_turn_falls_back_to_estimate_without_usage() -> None:
    agent = _agent(_UsageLLM(ChatResponse(text="hello")))

    events = [e for e in agent.turn("hi") if e.kind == "context_usage"]

    assert len(events) == 1
    payload = events[0].payload
    assert payload["estimated"] is True
    assert payload["window"] == 1_000_000
    assert payload["used"] > 0  # system + user + assistant text counted


def test_context_usage_event_precedes_final() -> None:
    agent = _agent(_UsageLLM(ChatResponse(text="done")))
    kinds = [e.kind for e in agent.turn("hi")]
    assert kinds.index("context_usage") < kinds.index("final")


def test_estimate_context_usage_snapshot() -> None:
    agent = _agent(_UsageLLM(ChatResponse(text="x")))
    agent.conversation.add_user("一个比较长的中文问题，用来占用一些上下文空间。")
    payload = agent.estimate_context_usage()
    assert payload["estimated"] is True
    assert payload["window"] == 1_000_000
    assert payload["used"] > 0
