"""Doc base registration: doc_search always, doc_read online + vision-gated.

Replaces the old RAG opt-in tests — the doc base superseded the embedding
knowledge base, so there is no `enable_knowledge` flag any more.
"""

from __future__ import annotations

from src.core import bootstrap
from src.llm.base import ChatResponse, LLMProvider


class _FakeVision(LLMProvider):
    name = "fake-vision"

    def chat(self, messages, tools=None) -> ChatResponse:
        return ChatResponse(text="")


def _names(*, offline: bool, vision: LLMProvider | None) -> set[str]:
    reg = bootstrap._build_tools(offline=offline, vision=vision)
    return {tool.name for tool in reg.all()}


def test_doc_search_registers_offline() -> None:
    # The doc base reads a committed manifest — no network, so it is available
    # even offline (unlike the old online-only knowledge_search).
    names = _names(offline=True, vision=None)
    assert "doc_search" in names
    assert "doc_read" not in names  # read shells out + needs vision


def test_doc_read_registers_online_with_vision() -> None:
    names = _names(offline=False, vision=_FakeVision())
    assert "doc_search" in names
    assert "doc_read" in names
    assert "pku3b_assignments" in names  # other online tools still register


def test_doc_read_skipped_without_vision() -> None:
    # Online but no Kimi key → no vision provider → doc_read is omitted.
    names = _names(offline=False, vision=None)
    assert "doc_search" in names
    assert "doc_read" not in names


def test_knowledge_search_no_longer_registered() -> None:
    online = _names(offline=False, vision=_FakeVision())
    assert "knowledge_search" not in online


def test_build_vision_llm_returns_none_without_key(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_KIMI_KEY_PATHS", ())
    assert bootstrap.build_vision_llm() is None
