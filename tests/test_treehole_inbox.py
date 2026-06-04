"""Unit coverage for the treehole unread accumulator.

`monitor.check()` returns only the delta since the dashboard's last poll, so
the dashboard must accumulate to keep an unread reply visible until viewed.
These tests pin the merge semantics (union by cid, earliest baseline, derived
delta) and the store's persist/load/clear without any Qt or network.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.tools.treehole_updates import TreeholeInboxStore, merge_treehole_updates


def _update(pid, old, new, comments=None):
    return {
        "pid": pid,
        "old_reply": old,
        "new_reply": new,
        "delta": new - old,
        "text": f"hole {pid}",
        "new_comments": comments or [],
    }


def _comment(cid, text="hi"):
    return {"cid": cid, "text": text, "name_tag": "洞友", "timestamp": cid}


def test_merge_accumulates_distinct_holes() -> None:
    first = [_update("1", 2, 3, [_comment(10)])]
    second = [_update("2", 0, 1, [_comment(20)])]
    merged = merge_treehole_updates(first, second)
    pids = {e["pid"] for e in merged}
    assert pids == {"1", "2"}


def test_merge_unions_comments_by_cid_for_same_hole() -> None:
    first = [_update("1", 2, 3, [_comment(10)])]
    second = [_update("1", 3, 5, [_comment(11), _comment(12)])]
    merged = merge_treehole_updates(first, second)
    assert len(merged) == 1
    entry = merged[0]
    assert [c["cid"] for c in entry["new_comments"]] == [10, 11, 12]
    # baseline is the earliest old_reply (2), count is the latest new_reply (5)
    assert entry["old_reply"] == 2
    assert entry["new_reply"] == 5
    assert entry["delta"] == 3


def test_merge_does_not_double_count_repeated_comment() -> None:
    poll = [_update("1", 0, 1, [_comment(10)])]
    merged = merge_treehole_updates([], poll)
    merged_again = merge_treehole_updates(merged, poll)
    assert len(merged_again) == 1
    assert [c["cid"] for c in merged_again[0]["new_comments"]] == [10]


def test_merge_delta_never_undercounts_shown_comments() -> None:
    # Count delta (1) is smaller than the number of fetched comments (3); the
    # display invariant hidden = delta - shown must stay >= 0.
    poll = [_update("1", 4, 5, [_comment(10), _comment(11), _comment(12)])]
    merged = merge_treehole_updates([], poll)
    assert merged[0]["delta"] >= len(merged[0]["new_comments"])


def test_merge_empty_poll_is_idempotent() -> None:
    base = merge_treehole_updates([], [_update("1", 0, 2, [_comment(10)])])
    assert merge_treehole_updates(base, []) == base


def test_merge_ignores_entries_without_pid() -> None:
    merged = merge_treehole_updates([], [{"old_reply": 0, "new_reply": 1}])
    assert merged == []


def test_store_in_memory_when_no_path() -> None:
    store = TreeholeInboxStore()
    store.merge([_update("1", 0, 2, [_comment(10), _comment(11)])])
    assert store.unread_count() == 2
    assert len(store.entries()) == 1


def test_store_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    store = TreeholeInboxStore(path)
    store.merge([_update("1", 0, 3, [_comment(10)])])
    assert path.exists()

    reopened = TreeholeInboxStore(path)
    assert reopened.unread_count() == store.unread_count()
    assert [e["pid"] for e in reopened.entries()] == ["1"]


def test_store_clear_empties_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    store = TreeholeInboxStore(path)
    store.merge([_update("1", 0, 1, [_comment(10)])])
    store.clear()
    assert store.unread_count() == 0
    assert json.loads(path.read_text())["entries"] == []


def test_store_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    path.write_text("not json{")
    store = TreeholeInboxStore(path)
    assert store.entries() == []
