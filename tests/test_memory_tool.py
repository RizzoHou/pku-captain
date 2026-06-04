"""Unit tests for `MemoryTool` — the agent-facing wrapper over MemoryStore."""

from __future__ import annotations

import pytest

from src.core.memory import MemoryStore
from src.tools.memory import MemoryTool


@pytest.fixture()
def tool(tmp_path) -> MemoryTool:
    return MemoryTool(store=MemoryStore(tmp_path / "memory.json"))


def test_set_then_get(tool: MemoryTool) -> None:
    set_result = tool.invoke({"action": "set", "key": "name", "value": "侯宇泽"})
    assert set_result.success
    assert set_result.data["value"] == "侯宇泽"

    get_result = tool.invoke({"action": "get", "key": "name"})
    assert get_result.success
    assert get_result.data["value"] == "侯宇泽"


def test_remember_stores_free_text(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "remember", "text": "我住在燕园"})
    assert result.success
    assert result.data["value"] == "我住在燕园"
    # No key was supplied, yet the entry is retrievable via list.
    listed = tool.invoke({"action": "list"})
    assert any(e["value"] == "我住在燕园" for e in listed.data)


def test_remember_requires_text(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "remember", "text": "  "})
    assert not result.success
    assert "text" in result.error


def test_set_requires_key(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "set", "value": "x"})
    assert not result.success
    assert "key" in result.error


def test_set_requires_value(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "set", "key": "name"})
    assert not result.success
    assert "value" in result.error


def test_get_missing(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "get", "key": "ghost"})
    assert not result.success


def test_list_returns_all(tool: MemoryTool) -> None:
    tool.invoke({"action": "set", "key": "a", "value": "1"})
    tool.invoke({"action": "set", "key": "b", "value": "2"})
    result = tool.invoke({"action": "list"})
    assert result.success
    assert {e["key"] for e in result.data} == {"a", "b"}


def test_delete_existing_and_missing(tool: MemoryTool) -> None:
    tool.invoke({"action": "set", "key": "k", "value": "v"})
    assert tool.invoke({"action": "delete", "key": "k"}).success
    assert not tool.invoke({"action": "delete", "key": "k"}).success


def test_unknown_action(tool: MemoryTool) -> None:
    result = tool.invoke({"action": "frobnicate"})
    assert not result.success
    assert "unknown action" in result.error


def test_writes_reach_injected_store(tmp_path) -> None:
    # The store passed in is the one written to — the wiring build_agent
    # relies on so the Agent can read back what the tool stored.
    store = MemoryStore(tmp_path / "memory.json")
    MemoryTool(store=store).invoke({"action": "set", "key": "lang", "value": "zh"})
    assert store.get("lang").value == "zh"
