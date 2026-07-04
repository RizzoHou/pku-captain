"""KimiProvider — Moonshot AI's Kimi K2.6, a full vision-capable chat brain.

Kimi's API is OpenAI-compatible, so this mirrors `DeepSeekProvider`'s
structure: explicit key + model in the constructor, `requests` directly
(no `openai` SDK), OpenAI-format message conversion, SSE streaming, and a
`thinking` mode that returns `reasoning_content`.

Kimi K2.6 (`kimi-k2.6`) is natively multimodal: text + image input, a 256k
context window, thinking/non-thinking modes, and tool calls. This is what
makes it a selectable chat brain *and* the engine doc_read feeds page images
to directly. Image input rides the same `content`-as-list channel as the
OpenAI vision format: the base `ChatMessage` only types `content` as `str`,
so multimodal callers pass a list of content parts at runtime (annotations
are not enforced); build them with `image_part()` / `text_part()`.

Differences from `DeepSeekProvider`: thinking is toggled with a
`{"thinking": {"type": "enabled"|"disabled"}}` body field rather than
`reasoning_effort`, and the endpoint is Moonshot's. Verified live against
`kimi-k2.6` on `https://api.moonshot.cn/v1` (2026-06-06): thinking returns
`reasoning_content`, SSE carries reasoning + content + usage deltas, tools
work under `tool_choice:"auto"`, and replaying `reasoning_content` on later
turns is accepted but not required (unlike DeepSeek, which 400s without it).
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
    image_part,
    text_part,
)

# Re-exported for callers that historically imported the multimodal content
# helpers from here; they now live in `llm.base` (generic OpenAI vision format).
__all__ = ["KimiAPIError", "KimiProvider", "image_part", "text_part"]


class KimiAPIError(RuntimeError):
    """Raised when the Kimi API returns a non-2xx response."""


class KimiProvider(LLMProvider):
    name: ClassVar[str] = "kimi"
    # Kimi K2.6 accepts a 256k-token context window — smaller than DeepSeek's
    # 1M, so the GUI context meter must re-read this on every model switch.
    context_window: ClassVar[int] = 256_000

    def __init__(
        self,
        api_key: str,
        model: str = "kimi-k2.6",
        base_url: str = "https://api.moonshot.cn/v1",
        timeout: float = 120.0,
        thinking: bool = True,
        context_window: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.thinking = thinking
        # A user-configured window (positive int) shadows the ClassVar default;
        # blank/None keeps the built-in 256k so the meter matches Kimi K2.6.
        if context_window is not None and context_window > 0:
            self.context_window = int(context_window)

    def _build_body(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(m) for m in messages],
        }
        # Moonshot toggles reasoning with a `thinking` object (not DeepSeek's
        # `reasoning_effort`). Enabled is the model default; we send it
        # explicitly so the wire format is unambiguous either way.
        body["thinking"] = {"type": "enabled" if self.thinking else "disabled"}
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            # Under thinking mode Moonshot only accepts "auto" / "none".
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
            raise KimiAPIError(f"Kimi API {resp.status_code}: {resp.text}")

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
                raise KimiAPIError(f"Kimi API {resp.status_code}: {resp.text}")

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            usage_raw: dict[str, Any] | None = None
            # Iterate raw BYTES, not `decode_unicode=True`: that decodes each
            # network chunk independently, corrupting a multi-byte UTF-8
            # character split across a chunk boundary (Kimi streams long Chinese
            # reasoning_content, so this fires constantly). A line break (0x0A)
            # never splits a UTF-8 sequence, so decoding each whole line is safe.
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
        # Replaying reasoning_content is optional for Kimi (verified: omitting
        # it returns 200), but we send it for parity with DeepSeek so the model
        # can build on its prior thinking.
        if m.reasoning_content is not None:
            out["reasoning_content"] = m.reasoning_content
        return out
    # system / user — `content` may be a plain string or a list of multimodal
    # content parts (text_part / image_part); pass either through.
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
    current = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
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
