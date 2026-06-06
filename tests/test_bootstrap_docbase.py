"""Doc base + chat-model registration.

`doc_search` registers in every mode (committed manifest). The image-feeding
`doc_read` tool is brain-gated: never registered by `_build_tools`, only added
by `apply_chat_model` while the active brain is vision-capable (Kimi).
"""

from __future__ import annotations

from src.core import bootstrap
from src.llm.deepseek import DeepSeekProvider
from src.llm.echo import EchoLLMProvider
from src.llm.kimi import KimiProvider
from src.tools.base import ToolRegistry


def _names(*, offline: bool) -> set[str]:
    reg = bootstrap._build_tools(offline=offline)
    return {tool.name for tool in reg.all()}


def test_doc_search_registers_in_every_mode() -> None:
    # The doc base reads a committed manifest — no network — so search is
    # available offline too (unlike the old online-only knowledge_search). The
    # image tool doc_read is brain-gated and never comes from _build_tools.
    for offline in (True, False):
        names = _names(offline=offline)
        assert "doc_search" in names
        assert "doc_read" not in names


def test_knowledge_search_no_longer_registered() -> None:
    assert "knowledge_search" not in _names(offline=False)


def test_set_doc_read_registered_toggles_idempotently() -> None:
    reg = ToolRegistry()
    bootstrap._set_doc_read_registered(reg, True)
    assert "doc_read" in reg
    bootstrap._set_doc_read_registered(reg, True)  # idempotent add
    assert "doc_read" in reg
    bootstrap._set_doc_read_registered(reg, False)
    assert "doc_read" not in reg
    bootstrap._set_doc_read_registered(reg, False)  # idempotent remove
    assert "doc_read" not in reg


def test_apply_chat_model_gates_doc_read(monkeypatch, tmp_path) -> None:
    # Build a minimal agent, then switch brains and assert doc_read tracks the
    # brain's vision capability. Keys are faked so the test needs no secrets.
    key = tmp_path / "k.txt"
    key.write_text("fake-key", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_find_key_path", lambda paths: key)

    agent = bootstrap.build_agent(offline=True)  # echo brain, no doc_read
    assert "doc_read" not in agent.tools

    bootstrap.apply_chat_model(agent, "kimi", offline=False)
    assert agent.llm.name == "kimi"
    assert "doc_read" in agent.tools  # vision brain → image tool registered

    bootstrap.apply_chat_model(agent, "deepseek", offline=False)
    assert agent.llm.name == "deepseek"
    assert "doc_read" not in agent.tools  # text brain → removed


def test_build_chat_llm_offline_is_echo() -> None:
    assert isinstance(bootstrap.build_chat_llm("kimi", offline=True), EchoLLMProvider)
    assert isinstance(
        bootstrap.build_chat_llm("deepseek", offline=True), EchoLLMProvider
    )


def test_build_chat_llm_unknown_model_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        bootstrap.build_chat_llm("nope", offline=False)


def test_build_chat_llm_constructs_named_brains(monkeypatch, tmp_path) -> None:
    key = tmp_path / "k.txt"
    key.write_text("fake-key", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_find_key_path", lambda paths: key)

    kimi = bootstrap.build_chat_llm("kimi", offline=False)
    assert isinstance(kimi, KimiProvider)
    assert kimi.model == "kimi-k2.6"
    assert kimi.context_window == 256_000

    deepseek = bootstrap.build_chat_llm("deepseek", offline=False)
    assert isinstance(deepseek, DeepSeekProvider)
    assert deepseek.context_window == 1_000_000


def test_available_chat_models_offline_is_empty() -> None:
    assert bootstrap.available_chat_models(offline=True) == []


def test_available_chat_models_lists_keyed_brains(monkeypatch, tmp_path) -> None:
    key = tmp_path / "k.txt"
    key.write_text("fake-key", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_find_key_path", lambda paths: key)
    models = dict(bootstrap.available_chat_models(offline=False))
    assert models == {"deepseek": "DeepSeek V4 Pro", "kimi": "Kimi K2.6"}


def test_build_vision_llm_and_doc_reader_none_without_key(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_KIMI_KEY_PATHS", ())
    assert bootstrap.build_vision_llm() is None
    assert bootstrap.build_doc_reader() is None
