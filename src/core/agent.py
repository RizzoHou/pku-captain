"""Agent kernel.

Holds the LLMProvider + ToolRegistry + WorkflowRegistry + Conversation.
Drives the tool-calling loop: ask the LLM with the tool schema; if the
LLM requests tool calls, dispatch them and feed results back; repeat
until the LLM returns a plain text reply or the iteration cap is hit.

`turn()` yields events so the UI tool-call panel can render the call
sequence as it happens, not just the final answer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import (
    ChatMessage,
    LLMProvider,
    estimate_tokens,
    image_part,
    text_part,
)
from ..tools.base import ToolRegistry
from ..workflows.base import WorkflowRegistry
from .conversation import Conversation
from .memory import MemoryStore, render_memory_context

# Shown (and persisted as the assistant turn's content) when the user stops a
# turn mid-flight. Kept identical between the `final` event and the conversation
# message so the rendered bubble matches what reloads from a saved session.
_CANCELLED_NOTE = "（已被用户中断）"


@dataclass
class AgentEvent:
    """Emitted as the agent processes a turn."""

    # "assistant_delta" | "reasoning_delta" | "llm_response"
    # | "tool_call" | "tool_result" | "context_usage" | "final"
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

    def turn(
        self,
        user_message: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> Iterator[AgentEvent]:
        """Process one user turn. Yields events as they happen.

        ``cancelled`` is a cheap predicate polled cooperatively at the safe
        boundaries between blocking I/O — before each LLM call, per streamed
        token, and before each tool dispatch. It can't interrupt a call already
        in flight (an HTTP request or subprocess), but it stops the loop at the
        next checkpoint and leaves ``Conversation`` in a valid state: every
        cancel path ends with a content-only assistant message so the
        user→assistant alternation stays clean for the next turn, and any
        not-yet-dispatched tool call gets a cancelled result so no
        ``assistant(tool_calls)`` is left with a missing answer. The worker
        passes a ``threading.Event.is_set`` here (see ``AgentWorker``).
        """
        self.conversation.add_user(user_message)
        tool_schema = self.tools.to_openai_schema()

        def is_cancelled() -> bool:
            return cancelled is not None and cancelled()

        for _ in range(self.max_tool_iterations):
            if is_cancelled():
                yield from self._yield_cancelled()
                return

            response = None
            partial_text: list[str] = []
            cancelled_mid_stream = False
            try:
                for stream_event in self.llm.stream_chat(
                    self._messages_for_llm(),
                    tools=tool_schema,
                ):
                    if is_cancelled():
                        cancelled_mid_stream = True
                        break
                    if stream_event.reasoning_delta:
                        yield AgentEvent(
                            kind="reasoning_delta",
                            payload={"text": stream_event.reasoning_delta},
                        )
                    if stream_event.delta:
                        partial_text.append(stream_event.delta)
                        yield AgentEvent(
                            kind="assistant_delta",
                            payload={"text": stream_event.delta},
                        )
                    if stream_event.response is not None:
                        response = stream_event.response
                if not cancelled_mid_stream and response is None:
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

            if cancelled_mid_stream:
                # Stopped before a response landed; keep whatever streamed so the
                # bubble (and the saved turn) shows the partial answer + note.
                yield from self._yield_cancelled("".join(partial_text))
                return

            yield AgentEvent(kind="llm_response", payload={"text": response.text})

            self.conversation.add_assistant(
                response.text,
                response.tool_calls,
                reasoning_content=response.reasoning_content,
            )
            yield AgentEvent(
                kind="context_usage", payload=self._usage_payload(response.usage)
            )

            if not response.tool_calls:
                yield AgentEvent(kind="final", payload={"text": response.text})
                return

            # Page images a vision tool (doc_read) produced this iteration. They
            # are injected as one multimodal user message *after* every tool
            # result is recorded, so the assistant(tool_calls) → tool(results)
            # → user(images) order stays valid and a vision-capable brain (Kimi)
            # reads the pages on the next iteration.
            pending_images: list[str] = []
            pending_notes: list[str] = []
            for index, call in enumerate(response.tool_calls):
                if is_cancelled():
                    # Answer every still-pending call so the assistant(tool_calls)
                    # message above keeps a result for each id, then stop. The
                    # tool_call events for these were never emitted, so the GUI
                    # has no dangling rows to resolve.
                    for pending in response.tool_calls[index:]:
                        self.conversation.add_tool_result(
                            call_id=pending.id,
                            name=pending.name,
                            content=f"ERROR: {_CANCELLED_NOTE}",
                        )
                    yield from self._yield_cancelled()
                    return
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
                if result.images:
                    pending_images.extend(result.images)
                    note = ""
                    if isinstance(result.data, dict):
                        note = str(result.data.get("note") or result.data.get("title") or "")
                    if note:
                        pending_notes.append(note)

            if pending_images:
                label = "；".join(pending_notes) or "文档页面"
                parts = [image_part(uri) for uri in pending_images]
                parts.append(
                    text_part(f"以上是{label}的页面图片，请据此回答用户的问题。")
                )
                self.conversation.add_user_parts(parts)

        text = (
            f"工具调用已达到上限（{self.max_tool_iterations} 轮）。"
            "我已停止继续调用工具，避免无限循环；请缩小问题范围或重新发起查询。"
        )
        self.conversation.add_assistant(text)
        yield AgentEvent(kind="final", payload={"text": text})

    def _yield_cancelled(self, partial_text: str = "") -> Iterator[AgentEvent]:
        """Record a user-interrupted turn and emit its closing ``final`` event.

        Always appends a content-only assistant message (no tool_calls, no
        reasoning_content — matching the synthetic max-iteration / context-length
        messages) so the conversation stays a valid user→assistant alternation
        whatever boundary the cancel hit. Any partial streamed answer is kept
        above the note so the user doesn't lose what they already saw.
        """
        text = (
            f"{partial_text}\n\n{_CANCELLED_NOTE}"
            if partial_text.strip()
            else _CANCELLED_NOTE
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

    def estimate_context_usage(self) -> dict[str, Any]:
        """Estimated context occupation of the current conversation.

        Used to seed/refresh the GUI meter outside a live turn — a new chat, a
        restored session, or offline where the API reports no token usage. The
        proactive complement to ``_is_context_length_error`` (the reactive guard
        that fires once the window is actually blown). Estimates from the same
        snapshot the next request would send, so it includes the folded-in
        memory block; ``used`` is therefore approximate (``estimated=True``).
        """
        return self._usage_payload(None)

    def _usage_payload(self, usage: Any) -> dict[str, Any]:
        """Build a ``context_usage`` payload, preferring real API token counts.

        Falls back to a heuristic estimate of the current LLM-bound snapshot
        when the provider reported no ``usage`` (Echo / non-usage providers).
        """
        window = getattr(self.llm, "context_window", 0) or 0
        if usage is not None:
            return {"used": usage.total_tokens, "window": window, "estimated": False}
        return {
            "used": estimate_tokens(self._messages_for_llm()),
            "window": window,
            "estimated": True,
        }


def _is_context_length_error(exc: Exception) -> bool:
    # Match context-length signals specifically; a bare "exceed" would also
    # swallow quota / rate-limit errors ("exceeded your quota") and mislabel
    # them as an over-long history.
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "maximum context length",
        "context length",
        "context_length_exceeded",
        "too many tokens",
        "token limit",
        "reduce the length of the messages",
    )
    return any(marker in text for marker in markers)
