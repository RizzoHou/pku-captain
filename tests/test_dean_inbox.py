"""Unit coverage for the dean items accumulator.

Each poll returns the full current first-page snapshot per source; the dashboard
must accumulate (union by ``key``) so an item is never lost when it drops off
page 1 — the card shows a recency window and the rest moves to history. These
tests pin the merge semantics (union by key, earliest first_seen, latest mutable
fields) and the store's persist/load without any Qt or network.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.tools.dean_updates import DeanInboxStore, merge_dean_updates

_NOW = "2026-06-05T12:00:00+08:00"
_EARLIER = "2026-01-01T09:00:00+08:00"


def _item(key, *, title="标题", source="notice", url="u", date="", item_id="1"):
    return {
        "key": key,
        "source": source,
        "source_label": "通知公告",
        "title": title,
        "url": url,
        "date": date,
        "item_id": item_id,
    }


def test_merge_accumulates_distinct_keys() -> None:
    first = [_item("notice:1")]
    second = [_item("notice:2", item_id="2")]
    merged = merge_dean_updates(first, second, now=_NOW)
    assert {e["key"] for e in merged} == {"notice:1", "notice:2"}


def test_merge_stamps_first_seen_on_new_items() -> None:
    merged = merge_dean_updates([], [_item("notice:1")], now=_NOW)
    assert merged[0]["first_seen"] == _NOW


def test_merge_preserves_earliest_first_seen() -> None:
    base = merge_dean_updates([], [_item("notice:1")], now=_EARLIER)
    # A later re-poll must not reset first_seen — windowing relies on the
    # earliest observation for date-less sources.
    again = merge_dean_updates(base, [_item("notice:1", title="改名")], now=_NOW)
    assert len(again) == 1
    assert again[0]["first_seen"] == _EARLIER
    assert again[0]["title"] == "改名"  # mutable field tracks the latest snapshot


def test_merge_is_idempotent_on_resnapshot() -> None:
    base = merge_dean_updates([], [_item("notice:1")], now=_NOW)
    again = merge_dean_updates(base, [_item("notice:1")], now=_NOW)
    assert again == base


def test_merge_ignores_entries_without_key() -> None:
    merged = merge_dean_updates([], [{"title": "无 key"}], now=_NOW)
    assert merged == []


def test_store_in_memory_when_no_path() -> None:
    store = DeanInboxStore()
    store.merge([_item("notice:1"), _item("notice:2", item_id="2")])
    assert len(store.entries()) == 2
    assert all(e.get("first_seen") for e in store.entries())


def test_store_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "dean_inbox.json"
    store = DeanInboxStore(path)
    store.merge([_item("notice:1")])
    assert path.exists()

    reopened = DeanInboxStore(path)
    assert [e["key"] for e in reopened.entries()] == ["notice:1"]


def test_store_never_loses_items_across_empty_poll(tmp_path: Path) -> None:
    path = tmp_path / "dean_inbox.json"
    store = DeanInboxStore(path)
    store.merge([_item("notice:1")])
    store.merge([])  # an empty poll must not drop the accumulated item
    assert [e["key"] for e in store.entries()] == ["notice:1"]
    assert json.loads(path.read_text())["entries"][0]["key"] == "notice:1"


def test_store_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "dean_inbox.json"
    path.write_text("not json{")
    store = DeanInboxStore(path)
    assert store.entries() == []
