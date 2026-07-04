"""DeepSeekProvider — DeepSeek chat LLM via its OpenAI-compatible API.

Default model is `deepseek-v4-pro` with reasoning `effort=max`. Constructor
takes the key + model explicitly; the caller (smoke script, app entrypoint)
is responsible for loading credentials. Uses `requests` directly to avoid
pulling in the `openai` SDK.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, ClassVar

import requests

from .base import (
    ChatMessage,
    ChatResponse,
    ChatStreamEvent,
    LLMProvider,
    TokenUsage,
    ToolCall,
)


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek API returns a non-2xx response."""


class DeepSeekProvider(LLMProvider):
    name: ClassVar[str] = "deepseek"
    # DeepSeek V4 accepts a 1M-token context window.
    context_window: ClassVar[int] = 1_000_000

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        effort: str = "max",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 120.0,
        thinking: bool = True,
        context_window: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.effort = effort
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.thinking = thinking
        # A user-configured window (positive int) shadows the ClassVar default;
        # blank/None keeps the built-in 1M so the meter matches DeepSeek V4.
        if context_window is not None and context_window > 0:
            self.context_window = int(context_window)

    def _build_body(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Assemble the request body.

        With `thinking=True` (the default), this is byte-identical to the
        historical body (`{model, messages, reasoning_effort, [stream],
        [tools]}`) so the GUI's main render path is unchanged. With
        `thinking=False` (the flash titler), `reasoning_effort` is dropped in
        favour of the non-think toggle `{"thinking": {"type": "disabled"}}`.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(m) for m in messages],
        }
        if self.thinking:
            body["reasoning_effort"] = self.effort
        else:
            body["thinking"] = {"type": "disabled"}
        if stream:
            body["stream"] = True
            # Ask for the trailing usage chunk; without this an SSE stream omits
            # token accounting entirely (OpenAI-compatible behaviour).
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        body = self._build_body(messages, tools, stream=False)

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise DeepSeekAPIError(
                f"DeepSeek API {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        text = msg.get("content") or ""
        reasoning = msg.get("reasoning_content")
        raw_calls = msg.get("tool_calls") or []
        calls = [
            ToolCall(
                id=c["id"],
                name=c["function"]["name"],
                arguments=_parse_arguments(c["function"].get("arguments", "{}")),
            )
            for c in raw_calls
        ]
        usage = _parse_usage(data.get("usage"))
        return ChatResponse(
            text=text, tool_calls=calls, reasoning_content=reasoning, usage=usage
        )

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatStreamEvent]:
        body = self._build_body(messages, tools, stream=True)

        with requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=self.timeout,
            stream=True,
        ) as resp:
            if resp.status_code >= 400:
                raise DeepSeekAPIError(
                    f"DeepSeek API {resp.status_code}: {resp.text}"
                )

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            usage_raw: dict[str, Any] | None = None
            # Iterate raw BYTES, not `decode_unicode=True`: that decodes each
            # network chunk independently and corrupts a multi-byte UTF-8 char
            # split across a chunk boundary (a latent bug that bites once Chinese
            # reasoning_content streams). A line break never splits a UTF-8
            # sequence, so decoding each whole line is safe.
            for raw_bytes in resp.iter_lines():
                if not raw_bytes:
                    continue
                raw_line = raw_bytes.decode("utf-8", errors="replace")
                if not raw_line.startswith("data:"):
                    continue
                payload = raw_line.removeprefix("data:").strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                # The trailing usage chunk carries `usage` with empty `choices`;
                # read it before the guard below skips choice-less chunks.
                if event.get("usage"):
                    usage_raw = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    text_parts.append(piece)
                    yield ChatStreamEvent(delta=piece)
                reasoning_piece = delta.get("reasoning_content") or ""
                if reasoning_piece:
                    reasoning_parts.append(reasoning_piece)
                    yield ChatStreamEvent(reasoning_delta=reasoning_piece)
                for call_delta in delta.get("tool_calls") or []:
                    _merge_tool_call_delta(tool_calls, call_delta)

        yield ChatStreamEvent(
            response=ChatResponse(
                text="".join(text_parts),
                tool_calls=_tool_calls_from_stream(tool_calls),
                reasoning_content="".join(reasoning_parts) or None,
                usage=_parse_usage(usage_raw),
            )
        )


def _to_api_message(m: ChatMessage) -> dict[str, Any]:
    if m.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id,
            "content": m.content,
        }
    if m.role == "assistant":
        out: dict[str, Any] = {"role": "assistant", "content": m.content or None}
        if m.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.arguments, ensure_ascii=False),
                    },
                }
                for c in m.tool_calls
            ]
        if m.reasoning_content is not None:
            out["reasoning_content"] = m.reasoning_content
        return out
    out = {"role": m.role, "content": m.content}
    if m.name:
        out["name"] = m.name
    return out


def _parse_usage(raw: dict[str, Any] | None) -> TokenUsage | None:
    if not raw:
        return None
    prompt = int(raw.get("prompt_tokens", 0) or 0)
    completion = int(raw.get("completion_tokens", 0) or 0)
    total = raw.get("total_tokens")
    total = int(total) if total is not None else prompt + completion
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
    )


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _merge_tool_call_delta(
    calls: dict[int, dict[str, Any]],
    delta: dict[str, Any],
) -> None:
    index = int(delta.get("index", len(calls)))
    current = calls.setdefault(
        index,
        {"id": "", "name": "", "arguments": ""},
    )
    if delta.get("id"):
        current["id"] += delta["id"]
    function = delta.get("function") or {}
    if function.get("name"):
        current["name"] += function["name"]
    if function.get("arguments"):
        current["arguments"] += function["arguments"]


def _tool_calls_from_stream(calls: dict[int, dict[str, Any]]) -> list[ToolCall]:
    out: list[ToolCall] = []
    for index in sorted(calls):
        call = calls[index]
        if not call.get("name"):
            continue
        out.append(
            ToolCall(
                id=call.get("id") or f"call_{index}",
                name=call["name"],
                arguments=_parse_arguments(call.get("arguments", "{}")),
            )
        )
    return out
