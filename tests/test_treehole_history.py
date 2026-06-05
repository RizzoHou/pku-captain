"""Unit coverage for the treehole history accumulator.

Unlike the unread inbox (cleared on read), the history store is an append-only
log of every dated new reply, returned newest-first. These tests pin the
per-comment dedup, time ordering, persistence, and the clear it offers the
dialog's 清空历史 button — no Qt or network.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.tools.treehole_updates import TreeholeHistoryStore


def _comment(cid, text="hi", timestamp=None):
    return {
        "cid": cid,
        "text": text,
        "name_tag": "洞友",
        "timestamp": cid if timestamp is None else timestamp,
    }


def _update(pid, comments):
    return {"pid": pid, "text": f"hole {pid}", "new_comments": comments}


def test_history_records_each_comment() -> None:
    store = TreeholeHistoryStore()
    store.merge([_update("1", [_comment(10), _comment(11)])])
    assert store.count() == 2
    pids = {e["pid"] for e in store.entries()}
    assert pids == {"1"}


def test_history_orders_newest_first_by_timestamp() -> None:
    store = TreeholeHistoryStore()
    store.merge([
        _update("1", [_comment(10, timestamp=100)]),
        _update("2", [_comment(20, timestamp=300)]),
        _update("3", [_comment(30, timestamp=200)]),
    ])
    assert [e["timestamp"] for e in store.entries()] == [300, 200, 100]


def test_history_untimed_comment_sinks_to_bottom() -> None:
    store = TreeholeHistoryStore()
    store.merge([
        _update("1", [_comment(10, timestamp=None)]),
        _update("2", [_comment(20, timestamp=50)]),
    ])
    assert [e["cid"] for e in store.entries()] == ["20", "10"]


def test_history_idempotent_on_repeated_merge() -> None:
    store = TreeholeHistoryStore()
    poll = [_update("1", [_comment(10)])]
    store.merge(poll)
    store.merge(poll)
    assert store.count() == 1


def test_history_dedupes_by_pid_and_cid() -> None:
    # Same cid under different holes are distinct records.
    store = TreeholeHistoryStore()
    store.merge([_update("1", [_comment(10)]), _update("2", [_comment(10)])])
    assert store.count() == 2


def test_history_skips_count_only_updates() -> None:
    # A poll reporting only a reply-count increase has no datable message.
    store = TreeholeHistoryStore()
    store.merge([_update("1", [])])
    assert store.count() == 0


def test_history_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = TreeholeHistoryStore(path)
    store.merge([_update("1", [_comment(10, timestamp=42)])])
    assert path.exists()

    reopened = TreeholeHistoryStore(path)
    assert reopened.count() == 1
    assert reopened.entries()[0]["timestamp"] == 42
    # Reload keeps dedup state so a re-merge is still idempotent.
    reopened.merge([_update("1", [_comment(10, timestamp=42)])])
    assert reopened.count() == 1


def test_history_clear_empties_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = TreeholeHistoryStore(path)
    store.merge([_update("1", [_comment(10)])])
    store.clear()
    assert store.count() == 0
    assert json.loads(path.read_text())["records"] == []


def test_history_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("not json{")
    store = TreeholeHistoryStore(path)
    assert store.entries() == []
