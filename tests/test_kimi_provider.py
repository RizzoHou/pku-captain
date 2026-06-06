"""KimiProvider — full chat brain (body, reasoning replay, multimodal, SSE).

All HTTP is mocked, so the test is deterministic and needs no key/network.
"""

from __future__ import annotations

import json

from src.llm import kimi
from src.llm.base import ChatMessage, ToolCall, image_part, text_part
from src.llm.kimi import KimiProvider, _to_api_message


class _FakeResp:
    def __init__(self, *, status=200, json_data=None, text="", lines=None):
        self.status_code = status
        self._json = json_data or {}
        self.text = text
        self._lines = lines or []

    def json(self):
        return self._json

    def iter_lines(self):  # provider iterates raw bytes (UTF-8-safe)
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_build_body_thinking_toggle() -> None:
    on = KimiProvider(api_key="k")._build_body([], None, stream=False)
    assert on["thinking"] == {"type": "enabled"}
    assert on["model"] == "kimi-k2.6"
    off = KimiProvider(api_key="k", thinking=False)._build_body([], None, stream=False)
    assert off["thinking"] == {"type": "disabled"}


def test_context_window_is_256k() -> None:
    assert KimiProvider(api_key="k").context_window == 256_000


def test_to_api_message_replays_reasoning_and_passes_multimodal() -> None:
    asst = ChatMessage(
        role="assistant",
        content="hi",
        tool_calls=(ToolCall(id="c1", name="t", arguments={}),),
        reasoning_content="because",
    )
    out = _to_api_message(asst)
    assert out["reasoning_content"] == "because"
    assert out["tool_calls"][0]["function"]["name"] == "t"

    parts = [image_part("data:image/png;base64,x"), text_part("看图")]
    user = ChatMessage(role="user", content=parts)  # type: ignore[arg-type]
    assert _to_api_message(user)["content"] == parts


def test_chat_parses_reasoning_and_usage(monkeypatch) -> None:
    resp = _FakeResp(
        json_data={
            "choices": [{"message": {"content": "答案", "reasoning_content": "想"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    monkeypatch.setattr(kimi.requests, "post", lambda *a, **k: resp)
    out = KimiProvider(api_key="k").chat([ChatMessage(role="user", content="q")])
    assert out.text == "答案"
    assert out.reasoning_content == "想"
    assert out.usage.total_tokens == 15


def test_stream_chat_decodes_utf8_and_parses(monkeypatch) -> None:
    # Each SSE line is raw bytes; Chinese reasoning must decode intact (the
    # iter_lines(decode_unicode=True) bug corrupted multi-byte chars).
    def line(obj: dict) -> bytes:
        return ("data: " + json.dumps(obj, ensure_ascii=False)).encode("utf-8")

    lines = [
        line({"choices": [{"delta": {"reasoning_content": "历史"}}]}),
        line({"choices": [{"delta": {"content": "北大"}}]}),
        line({"choices": [{"delta": {"content": "数院"}}]}),
        line(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            }
        ),
        b"data: [DONE]",
    ]
    monkeypatch.setattr(kimi.requests, "post", lambda *a, **k: _FakeResp(lines=lines))

    events = list(
        KimiProvider(api_key="k").stream_chat([ChatMessage(role="user", content="q")])
    )
    reasoning = "".join(e.reasoning_delta for e in events if e.reasoning_delta)
    text = "".join(e.delta for e in events if e.delta)
    final = next(e.response for e in events if e.response is not None)
    assert reasoning == "历史"
    assert text == "北大数院"
    assert final.text == "北大数院"
    assert final.reasoning_content == "历史"
    assert final.usage.total_tokens == 5
