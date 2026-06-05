"""Agent kernel.

Holds the LLMProvider + ToolRegistry + WorkflowRegistry + Conversation.
Drives the tool-calling loop: ask the LLM with the tool schema; if the
LLM requests tool calls, dispatch them and feed results back; repeat
until the LLM returns a plain text reply or the iteration cap is hit.

`turn()` yields events so the UI tool-call panel can render the call
sequence as it happens, not just the final answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import ChatMessage, LLMProvider
from ..tools.base import ToolRegistry, ToolResult
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
        seen_tool_calls: set[tuple[str, str]] = set()
        treehole_actions: dict[str, int] = {"search": 0, "fetch": 0}

        for _ in range(self.max_tool_iterations):
            response = None
            try:
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
            except Exception as exc:
                if _is_context_length_error(exc):
                    text = (
                        "当前对话历史过长，已经超过模型可处理的上下文长度。"
                        "请新开一个对话，或先让我总结前面的内容后再继续。"
                    )
                    self.conversation.add_assistant(text)
                    yield AgentEvent(kind="final", payload={"text": text})
                    return
                raise
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
                signature = _tool_call_signature(call.name, call.arguments)
                if signature in seen_tool_calls:
                    error = "检测到同一工具被相同参数重复调用，已停止执行。"
                    yield AgentEvent(
                        kind="tool_call",
                        payload={"id": call.id, "name": call.name, "arguments": call.arguments},
                    )
                    yield AgentEvent(
                        kind="tool_result",
                        payload={
                            "id": call.id,
                            "name": call.name,
                            "result": ToolResult(success=False, error=error),
                        },
                    )
                    self.conversation.add_tool_result(
                        call_id=call.id,
                        name=call.name,
                        content=f"ERROR: {error}",
                    )
                    text = (
                        f"工具 `{call.name}` 被要求用相同参数重复调用。"
                        "我已停止继续调用工具，避免陷入循环；请换一种问法，"
                        "或指定需要我继续查询的具体内容。"
                    )
                    self.conversation.add_assistant(text)
                    yield AgentEvent(kind="final", payload={"text": text})
                    return
                seen_tool_calls.add(signature)
                yield AgentEvent(
                    kind="tool_call",
                    payload={"id": call.id, "name": call.name, "arguments": call.arguments},
                )
                limit_error = _treehole_call_limit_error(
                    call.name, call.arguments, treehole_actions
                )
                if limit_error is not None:
                    result = ToolResult(success=False, error=limit_error)
                    yield AgentEvent(
                        kind="tool_result",
                        payload={"id": call.id, "name": call.name, "result": result},
                    )
                    self.conversation.add_tool_result(
                        call_id=call.id,
                        name=call.name,
                        content=f"ERROR: {limit_error}",
                    )
                    continue
                result = self.tools.get(call.name).invoke(call.arguments)
                yield AgentEvent(
                    kind="tool_result",
                    payload={"id": call.id, "name": call.name, "result": result},
                )
                self.conversation.add_tool_result(
                    call_id=call.id,
                    name=call.name,
                    content=_serialize_tool_result(call.name, result),
                )

        text = (
            f"工具调用已达到上限（{self.max_tool_iterations} 轮）。"
            "我已停止继续调用工具，避免无限循环；请缩小问题范围或重新发起查询。"
        )
        self.conversation.add_assistant(text)
        yield AgentEvent(kind="final", payload={"text": text})

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


def _tool_call_signature(name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    if name == "treehole":
        action = str(arguments.get("action") or "").strip()
        if action == "search":
            keywords = _split_signature_keywords(str(arguments.get("keyword") or ""))
            payload = {
                "action": "search",
                "keywords": keywords[:3],
                "category": str(arguments.get("category") or "").strip(),
                "sort": str(arguments.get("sort") or "relevance").strip(),
            }
            return name, json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if action == "fetch":
            payload = {
                "action": "fetch",
                "pid": str(arguments.get("pid") or "").strip().lstrip("#"),
                "comment_mode": str(arguments.get("comment_mode") or "recent").strip(),
            }
            return name, json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return name, json.dumps(arguments, sort_keys=True, ensure_ascii=False)


def _treehole_call_limit_error(
    name: str, arguments: dict[str, Any], counters: dict[str, int]
) -> str | None:
    if name != "treehole":
        return None
    action = str(arguments.get("action") or "").strip()
    if action not in counters:
        return None
    if counters[action] >= 1:
        return (
            "本轮对话中树洞工具已完成一次 "
            f"{action}，为避免上下文过长和反复搜索，已拒绝继续调用。"
        )
    counters[action] += 1
    return None


_SIGNATURE_KEYWORD_RE = re.compile(r"[^\s,，;；、]+")


def _split_signature_keywords(text: str) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for match in _SIGNATURE_KEYWORD_RE.findall(text):
        keyword = match.strip()[:24]
        key = keyword.casefold()
        if keyword and key not in seen:
            seen.add(key)
            keywords.append(keyword)
    return keywords


def _serialize_tool_result(name: str, result: ToolResult) -> str:
    if not result.success:
        return f"ERROR: {result.error}"
    try:
        content = json.dumps(
            result.data,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    except TypeError:
        content = str(result.data)
    budget = 3_000 if name == "treehole" else 4_000
    return _truncate_text(content, budget)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 18)] + "\n...（已截断）"


def _is_context_length_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "maximum context length",
        "context length",
        "exceed",
        "too many tokens",
        "token limit",
    )
    return any(marker in text for marker in markers)
