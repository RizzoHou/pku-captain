"""Unit tests for the memory backend (`src.core.memory`).

Covers `MemoryStore` CRUD, persistence, corruption handling, thread
safety, and the `render_memory_context` helper that folds stored facts
into the agent's system prompt.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest

from src.core.memory import MemoryEntry, MemoryStore, render_memory_context


def _store(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.json")


# -- CRUD --------------------------------------------------------------------


def test_set_get_roundtrip(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("home_location", "Yan'an Garden")
    entry = store.get("home_location")
    assert entry is not None
    assert entry.key == "home_location"
    assert entry.value == "Yan'an Garden"


def test_set_returns_entry_with_iso_timestamp(tmp_path) -> None:
    entry = _store(tmp_path).set("name", "侯宇泽")
    assert isinstance(entry, MemoryEntry)
    # updated_at must be a parseable ISO-8601 timestamp with offset.
    parsed = datetime.fromisoformat(entry.updated_at)
    assert parsed.utcoffset() is not None


def test_set_overwrites_value(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("lang", "English")
    store.set("lang", "Chinese")
    assert store.get("lang").value == "Chinese"
    assert len(store.list()) == 1


def test_set_strips_key(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("  name  ", "侯宇泽")
    assert store.get("name").value == "侯宇泽"


@pytest.mark.parametrize("bad_key", ["", "   ", "\t\n"])
def test_set_empty_key_raises(tmp_path, bad_key) -> None:
    with pytest.raises(ValueError):
        _store(tmp_path).set(bad_key, "x")


def test_get_missing_returns_none(tmp_path) -> None:
    assert _store(tmp_path).get("nope") is None


def test_get_strips_key(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("major", "CS")
    assert store.get("  major  ") is not None


def test_list_sorted_by_key(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("zeta", "1")
    store.set("alpha", "2")
    store.set("mike", "3")
    assert [e.key for e in store.list()] == ["alpha", "mike", "zeta"]


def test_list_empty(tmp_path) -> None:
    assert _store(tmp_path).list() == []


def test_delete_existing_returns_true(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("k", "v")
    assert store.delete("k") is True
    assert store.get("k") is None


def test_delete_missing_returns_false(tmp_path) -> None:
    assert _store(tmp_path).delete("ghost") is False


def test_unicode_value_roundtrips(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("note", "住在燕园，喜欢用中文回复")
    assert store.get("note").value == "住在燕园，喜欢用中文回复"


# -- persistence -------------------------------------------------------------


def test_persistence_across_instances(tmp_path) -> None:
    path = tmp_path / "memory.json"
    MemoryStore(path).set("name", "侯宇泽")
    # A fresh instance pointed at the same file must see the write.
    assert MemoryStore(path).get("name").value == "侯宇泽"


def test_set_writes_through_immediately(tmp_path) -> None:
    path = tmp_path / "memory.json"
    MemoryStore(path).set("k", "v")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["entries"][0]["key"] == "k"


def test_delete_persists(tmp_path) -> None:
    path = tmp_path / "memory.json"
    store = MemoryStore(path)
    store.set("k", "v")
    store.delete("k")
    assert MemoryStore(path).list() == []


def test_missing_file_starts_empty(tmp_path) -> None:
    # No file on disk yet — construction must not raise.
    assert MemoryStore(tmp_path / "does_not_exist.json").list() == []


def test_corrupt_file_starts_empty(tmp_path) -> None:
    path = tmp_path / "memory.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    # Corrupt store loads empty rather than crashing.
    store = MemoryStore(path)
    assert store.list() == []
    # ...and is still writable.
    store.set("k", "v")
    assert store.get("k").value == "v"


def test_load_skips_non_string_keys(tmp_path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {"key": "good", "value": "1", "updated_at": "x"},
                    {"key": 123, "value": "2", "updated_at": "x"},
                    {"value": "3", "updated_at": "x"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert [e.key for e in MemoryStore(path).list()] == ["good"]


# -- thread safety -----------------------------------------------------------


def test_concurrent_set_no_lost_writes(tmp_path) -> None:
    path = tmp_path / "memory.json"
    store = MemoryStore(path)
    n = 32
    barrier = threading.Barrier(n)

    def writer(i: int) -> None:
        barrier.wait()  # maximize contention on the shared lock + flush
        store.set(f"key_{i:02d}", str(i))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.list()) == n
    # The on-disk file must remain valid JSON with every write present.
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert len(raw["entries"]) == n


# -- render_memory_context ---------------------------------------------------


def test_render_empty_returns_empty_string() -> None:
    assert render_memory_context([]) == ""


def test_render_lists_each_entry(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("name", "侯宇泽")
    store.set("home_location", "Yan'an Garden")
    block = render_memory_context(store.list())
    assert "Known facts about the user" in block
    assert "- name: 侯宇泽" in block
    assert "- home_location: Yan'an Garden" in block


def test_render_follows_list_order(tmp_path) -> None:
    store = _store(tmp_path)
    store.set("zeta", "1")
    store.set("alpha", "2")
    block = render_memory_context(store.list())
    # list() is sorted by key, so alpha precedes zeta in the rendered block.
    assert block.index("alpha") < block.index("zeta")
