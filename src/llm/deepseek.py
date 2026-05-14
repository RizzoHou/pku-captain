"""DeepSeekProvider — DeepSeek chat LLM via its OpenAI-compatible API.

Default model is `deepseek-v4-pro` with reasoning `effort=max`. Constructor
takes the key + model explicitly; the caller (smoke script, app entrypoint)
is responsible for loading credentials. Uses `requests` directly to avoid
pulling in the `openai` SDK.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import requests

from .base import ChatMessage, ChatResponse, LLMProvider, ToolCall


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek API returns a non-2xx response."""


class DeepSeekProvider(LLMProvider):
    name: ClassVar[str] = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        effort: str = "max",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.effort = effort
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
            "effort": self.effort,
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
        return ChatResponse(text=text, tool_calls=calls, reasoning_content=reasoning)


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


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}
