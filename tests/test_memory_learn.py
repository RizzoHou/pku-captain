"""Unit tests for `MemoryLearnService` — natural text → clean stored facts.

The parser is the feature: a too-strict JSON parse would make every real
DeepSeek reply silently fall back to a single verbatim blob. These tests
exercise fenced and prose-wrapped replies, not just clean arrays.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.core.memory import MemoryStore
from src.core.memory_learn import MemoryLearnService, _parse_facts
from src.llm.base import ChatMessage, ChatResponse, LLMProvider
from src.llm.echo import EchoLLMProvider


class FakeLLM(LLMProvider):
    """Returns a fixed reply text, or raises if constructed to."""

    name = "fake"

    def __init__(self, reply: str = "", *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        if self._raises:
            raise RuntimeError("llm down")
        return ChatResponse(text=self._reply)


def _service(tmp_path, llm: LLMProvider) -> tuple[MemoryLearnService, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.json")
    return MemoryLearnService(llm, store), store


# -- _parse_facts ------------------------------------------------------------


def test_parse_clean_array() -> None:
    assert _parse_facts('["住在燕园", "喜欢用中文"]') == ["住在燕园", "喜欢用中文"]


def test_parse_fenced_json() -> None:
    assert _parse_facts('```json\n["a", "b"]\n```') == ["a", "b"]


def test_parse_prose_wrapped() -> None:
    assert _parse_facts('Here are the facts: ["a", "b"]. Done.') == ["a", "b"]


def test_parse_filters_non_strings_and_blanks() -> None:
    assert _parse_facts('["a", 1, "  ", "  b  ", null]') == ["a", "b"]


@pytest.mark.parametrize("bad", ["", "not json at all", "{}", "[}", '{"a": 1}'])
def test_parse_garbage_returns_empty(bad: str) -> None:
    assert _parse_facts(bad) == []


# -- learn -------------------------------------------------------------------


def test_learn_splits_into_multiple_facts(tmp_path) -> None:
    service, store = _service(tmp_path, FakeLLM('["住在燕园", "喜欢用中文交流"]'))
    result = service.learn("我住在燕园，喜欢用中文交流")
    assert result.extracted is True
    assert result.stored == ["住在燕园", "喜欢用中文交流"]
    # Each fact is a separate retrievable entry.
    assert {e.value for e in store.list()} == {"住在燕园", "喜欢用中文交流"}


def test_learn_extracts_from_fenced_reply(tmp_path) -> None:
    service, store = _service(tmp_path, FakeLLM('```json\n["住在燕园"]\n```'))
    result = service.learn("我住在燕园")
    assert result.extracted is True
    assert result.stored == ["住在燕园"]
    assert len(store.list()) == 1


def test_learn_falls_back_to_verbatim_on_garbage(tmp_path) -> None:
    service, store = _service(tmp_path, FakeLLM("I could not produce JSON"))
    result = service.learn("我住在燕园")
    assert result.extracted is False
    assert result.stored == ["我住在燕园"]  # raw text stored as one entry
    assert store.list()[0].value == "我住在燕园"


def test_learn_falls_back_when_llm_raises(tmp_path) -> None:
    service, store = _service(tmp_path, FakeLLM(raises=True))
    result = service.learn("我住在燕园")
    assert result.extracted is False
    assert store.list()[0].value == "我住在燕园"


def test_learn_empty_extraction_falls_back_to_verbatim(tmp_path) -> None:
    # Model judged nothing worth remembering, but the user clicked 记住 —
    # store the raw text rather than dropping it.
    service, store = _service(tmp_path, FakeLLM("[]"))
    result = service.learn("随便说点什么")
    assert result.extracted is False
    assert store.list()[0].value == "随便说点什么"


def test_learn_offline_echo_degrades_to_verbatim(tmp_path) -> None:
    # The real offline provider: its echo is never valid JSON, so the
    # service degrades to verbatim without any offline special-casing.
    service, store = _service(tmp_path, EchoLLMProvider())
    result = service.learn("我住在燕园")
    assert result.extracted is False
    assert store.list()[0].value == "我住在燕园"


def test_learn_rejects_empty_text(tmp_path) -> None:
    service, _ = _service(tmp_path, FakeLLM("[]"))
    with pytest.raises(ValueError):
        service.learn("   ")
