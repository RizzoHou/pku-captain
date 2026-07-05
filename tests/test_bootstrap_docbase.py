"""Doc base + chat-model registration.

`doc_search` registers in every mode (committed manifest). The image-feeding
`doc_read` tool is brain-gated: never registered by `_build_tools`, only added
by `apply_chat_model` while the active role is vision-capable (`visual`).

Chat brains are two configurable *roles* now — `text` (default DeepSeek) and
`visual` (default Kimi) — each reading its endpoint / model / key from a
`CredentialStore`. Tests point the model layer at a tmp `secrets/` by
monkeypatching `bootstrap._store`.
"""

from __future__ import annotations

import pytest

from src.core import bootstrap
from src.core.credentials import CredentialStore
from src.llm.deepseek import DeepSeekProvider
from src.llm.echo import EchoLLMProvider
from src.llm.kimi import KimiProvider
from src.tools.base import ToolRegistry


def _configured_store(tmp_path) -> CredentialStore:
    """A store with both roles keyed, at a throwaway secrets dir."""
    store = CredentialStore(tmp_path / "secrets")
    store.save_model("text", api_key="fake-text-key")
    store.save_model("visual", api_key="fake-visual-key")
    return store


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
    # Build a minimal agent, then switch roles and assert doc_read tracks the
    # role's vision capability. The store is faked so no real secrets are read.
    store = _configured_store(tmp_path)
    monkeypatch.setattr(bootstrap, "_store", lambda: store)

    agent = bootstrap.build_agent(offline=True)  # echo brain, no doc_read
    assert "doc_read" not in agent.tools

    bootstrap.apply_chat_model(agent, "visual", offline=False)
    assert agent.llm.name == "kimi"  # visual role → Kimi provider identity
    assert "doc_read" in agent.tools  # vision role → image tool registered

    bootstrap.apply_chat_model(agent, "text", offline=False)
    assert agent.llm.name == "deepseek"  # text role → DeepSeek provider
    assert "doc_read" not in agent.tools  # text role → removed


def test_build_agent_reads_tool_rounds_from_store(monkeypatch, tmp_path) -> None:
    # build_agent threads the persisted 对话设置 limit into the Agent's loop cap
    # (default 8 when unset, the stored value otherwise).
    from src.core.credentials import TOOL_ROUNDS_DEFAULT

    store = _configured_store(tmp_path)
    monkeypatch.setattr(bootstrap, "_store", lambda: store)

    assert bootstrap.build_agent(offline=True).max_tool_iterations == TOOL_ROUNDS_DEFAULT
    store.save_tool_rounds(15)
    assert bootstrap.build_agent(offline=True).max_tool_iterations == 15


def test_build_chat_llm_offline_is_echo() -> None:
    assert isinstance(bootstrap.build_chat_llm("visual", offline=True), EchoLLMProvider)
    assert isinstance(bootstrap.build_chat_llm("text", offline=True), EchoLLMProvider)


def test_build_chat_llm_unknown_model_raises() -> None:
    with pytest.raises(ValueError):
        bootstrap.build_chat_llm("nope", offline=False)


def test_build_chat_llm_missing_key_raises(monkeypatch, tmp_path) -> None:
    # An unconfigured role (no key, no legacy file) raises rather than
    # silently building a keyless provider.
    empty = CredentialStore(tmp_path / "secrets")
    monkeypatch.setattr(bootstrap, "_store", lambda: empty)
    with pytest.raises(FileNotFoundError):
        bootstrap.build_chat_llm("text", offline=False)


def test_build_chat_llm_constructs_roles(monkeypatch, tmp_path) -> None:
    store = _configured_store(tmp_path)
    monkeypatch.setattr(bootstrap, "_store", lambda: store)

    visual = bootstrap.build_chat_llm("visual", offline=False)
    assert isinstance(visual, KimiProvider)
    assert visual.model == "kimi-k2.6"
    assert visual.context_window == 256_000

    text = bootstrap.build_chat_llm("text", offline=False)
    assert isinstance(text, DeepSeekProvider)
    assert text.model == "deepseek-v4-pro"
    assert text.context_window == 1_000_000


def test_build_chat_llm_honours_custom_endpoint(monkeypatch, tmp_path) -> None:
    # A user-set endpoint/model flows through to the provider — DeepSeek/Kimi
    # are only defaults.
    store = CredentialStore(tmp_path / "secrets")
    store.save_model(
        "text",
        api_key="k",
        base_url="https://proxy.example.com/v1",
        model="my-model",
    )
    monkeypatch.setattr(bootstrap, "_store", lambda: store)
    provider = bootstrap.build_chat_llm("text", offline=False)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.base_url == "https://proxy.example.com/v1"
    assert provider.model == "my-model"


def test_available_chat_models_offline_is_empty() -> None:
    assert bootstrap.available_chat_models(offline=True) == []


def test_available_chat_models_lists_keyed_roles(monkeypatch, tmp_path) -> None:
    store = _configured_store(tmp_path)
    monkeypatch.setattr(bootstrap, "_store", lambda: store)
    models = dict(bootstrap.available_chat_models(offline=False))
    assert models == {"text": "文本模型", "visual": "视觉模型"}


def test_available_chat_models_omits_unkeyed_role(monkeypatch, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_model("text", api_key="only-text")  # visual left unconfigured
    monkeypatch.setattr(bootstrap, "_store", lambda: store)
    assert dict(bootstrap.available_chat_models(offline=False)) == {"text": "文本模型"}


def test_build_vision_llm_and_doc_reader_none_without_key(monkeypatch, tmp_path) -> None:
    empty = CredentialStore(tmp_path / "secrets")
    monkeypatch.setattr(bootstrap, "_store", lambda: empty)
    assert bootstrap.build_vision_llm() is None
    assert bootstrap.build_doc_reader() is None
