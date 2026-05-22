"""KimiProvider — Moonshot AI's Kimi LLM, the project's vision channel.

Per the committed stack, DeepSeek carries chat and Kimi carries vision.
Kimi's API is OpenAI-compatible, so this mirrors `DeepSeekProvider`'s
structure: explicit key + model in the constructor, `requests` directly
(no `openai` SDK), and OpenAI-format message conversion.

Image input is Kimi's reason for existing here. The base `ChatMessage`
only types `content` as `str`, so multimodal callers pass a list of
content parts as `content` at runtime (annotations are not enforced);
build them with `image_part()` / `text_part()`. A plain-`str` `content`
is sent as-is. Kimi has no thinking mode, so `reasoning_content` stays
`None` on both the request and the response.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import requests

from .base import ChatMessage, ChatResponse, LLMProvider, ToolCall


class KimiAPIError(RuntimeError):
    """Raised when the Kimi API returns a non-2xx response."""


def text_part(text: str) -> dict[str, Any]:
    """A text content part for a multimodal Kimi message."""
    return {"type": "text", "text": text}


def image_part(url: str) -> dict[str, Any]:
    """An image content part for a multimodal Kimi message.

    `url` is either a remote URL or a `data:image/...;base64,...` URI.
    """
    return {"type": "image_url", "image_url": {"url": url}}


class KimiProvider(LLMProvider):
    name: ClassVar[str] = "kimi"

    def __init__(
        self,
        api_key: str,
        model: str = "moonshot-v1-8k-vision-preview",
        base_url: str = "https://api.moonshot.cn/v1",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_to_api_message(m) for m in messages],
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

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
        raw_calls = msg.get("tool_calls") or []
        calls = [
            ToolCall(
                id=c["id"],
                name=c["function"]["name"],
                arguments=_parse_arguments(c["function"].get("arguments", "{}")),
            )
            for c in raw_calls
        ]
        return ChatResponse(text=text, tool_calls=calls)


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
        return out
    # system / user — `content` may be a plain string or a list of
    # multimodal content parts (text_part / image_part); pass either through.
    out = {"role": m.role, "content": m.content}
    if m.name:
        out["name"] = m.name
    return out


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}
