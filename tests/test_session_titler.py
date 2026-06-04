"""SessionTitler: provider-backed titling with cleanup/truncation, and the
graceful heuristic fallback (offline / empty / raising). Uses fake providers
so no network is touched."""

from __future__ import annotations

from src.core.session_titler import SessionTitler
from src.llm.base import ChatMessage, ChatResponse


class _FakeProvider:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages, tools=None) -> ChatResponse:
        self.calls.append(messages)
        return ChatResponse(text=self._text)


class _RaisingProvider:
    def chat(self, messages, tools=None) -> ChatResponse:
        raise RuntimeError("network down")


def _convo() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="帮我查明天的课表和作业"),
        ChatMessage(role="assistant", content="好的"),
    ]


_HEURISTIC = "帮我查明天的课表和作业"  # 11 chars, under the truncation cap


def test_generate_uses_provider_and_strips_quotes() -> None:
    provider = _FakeProvider('  “课表查询”  ')
    titler = SessionTitler(provider)
    assert titler.generate(_convo()) == "课表查询"
    assert provider.calls  # the provider was actually called


def test_generate_truncates_long_title() -> None:
    titler = SessionTitler(_FakeProvider("一二三四五六七八九十十一十二十三十四十五十六十七十八"))
    title = titler.generate(_convo())
    assert title.endswith("…")
    assert len(title) == 18 + 1  # _MAX_TITLE_LEN + ellipsis


def test_none_provider_uses_heuristic() -> None:
    assert SessionTitler(None).generate(_convo()) == _HEURISTIC


def test_empty_provider_result_falls_back() -> None:
    assert SessionTitler(_FakeProvider("   \n  ")).generate(_convo()) == _HEURISTIC


def test_raising_provider_falls_back() -> None:
    assert SessionTitler(_RaisingProvider()).generate(_convo()) == _HEURISTIC


def test_no_user_message_returns_default() -> None:
    titler = SessionTitler(None)
    assert titler.generate([ChatMessage(role="system", content="sys")]) == "新会话"


def test_heuristic_never_echoes() -> None:
    # Offline path uses provider=None, so a title is never "echo: ...".
    assert not SessionTitler(None).generate(_convo()).startswith("echo:")


def test_heuristic_method_is_network_free() -> None:
    # The synchronous provisional title ignores the provider entirely.
    provider = _FakeProvider("应该不会被调用")
    assert SessionTitler(provider).heuristic(_convo()) == _HEURISTIC
    assert provider.calls == []
