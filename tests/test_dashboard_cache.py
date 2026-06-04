"""DashboardCache persistence + the GUI's "render only if changed" decision.

The store is a dumb per-card JSON cache; the change-detection that keeps a
silent startup refresh flicker-free lives in two pure helpers in
`src.ui.main_window` (`_signature` / `_should_render`), tested here without Qt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.dashboard_cache import DashboardCache

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from src.ui.main_window import _should_render, _signature  # noqa: E402


def test_save_get_round_trip(tmp_path: Path) -> None:
    cache = DashboardCache(tmp_path)
    data = {"assignments": [{"title": "hw1", "deadline_iso": "2026-06-10"}]}
    cache.save("pku3b_assignments", data)
    assert cache.get("pku3b_assignments") == data


def test_get_missing_key_returns_none(tmp_path: Path) -> None:
    assert DashboardCache(tmp_path).get("lecture") is None


def test_save_tolerates_non_json_native_value(tmp_path: Path) -> None:
    # save() uses default=str (mirroring the GUI's _signature) so a surprising
    # payload type stringifies instead of raising inside the Qt slot.
    from datetime import datetime

    cache = DashboardCache(tmp_path)
    cache.save("x", {"when": datetime(2030, 1, 1)})  # noqa: DTZ001 - test value
    got = cache.get("x")
    assert isinstance(got["when"], str)


def test_load_all_collects_every_card(tmp_path: Path) -> None:
    cache = DashboardCache(tmp_path)
    cache.save("lecture", [{"title": "talk"}])
    cache.save("treehole_updates", {"unread_count": 2})
    assert cache.load_all() == {
        "lecture": [{"title": "talk"}],
        "treehole_updates": {"unread_count": 2},
    }


def test_load_all_skips_corrupt_files(tmp_path: Path) -> None:
    cache = DashboardCache(tmp_path)
    cache.save("lecture", [{"title": "talk"}])
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    # The corrupt file is ignored; the good entry still loads.
    assert cache.load_all() == {"lecture": [{"title": "talk"}]}


def test_load_all_empty_dir(tmp_path: Path) -> None:
    assert DashboardCache(tmp_path / "missing").load_all() == {}


def test_newest_timestamp_none_when_empty(tmp_path: Path) -> None:
    assert DashboardCache(tmp_path).newest_timestamp() is None


def test_newest_timestamp_present_after_save(tmp_path: Path) -> None:
    cache = DashboardCache(tmp_path)
    cache.save("lecture", [])
    assert cache.newest_timestamp() is not None


def test_signature_ignores_dict_order_and_type_drift() -> None:
    # JSON round-trip turns a tuple into a list; sort_keys ignores ordering.
    fresh = {"a": 1, "b": [1, 2]}
    cached_after_reload = {"b": [1, 2], "a": 1}
    assert _signature(fresh) == _signature(cached_after_reload)
    assert _signature({"x": (1, 2)}) == _signature({"x": [1, 2]})


def test_signature_detects_real_change() -> None:
    assert _signature({"n": 1}) != _signature({"n": 2})


def test_should_render_loading_card_always_renders() -> None:
    # A spinner card must render even if the fresh data equals the cache,
    # or it is stranded on "加载中...".
    assert _should_render(loading=True, current_sig="x", fresh_sig="x") is True


def test_should_render_skips_unchanged_cached_card() -> None:
    assert _should_render(loading=False, current_sig="x", fresh_sig="x") is False


def test_should_render_repaints_changed_cached_card() -> None:
    assert _should_render(loading=False, current_sig="x", fresh_sig="y") is True


def test_should_render_uncached_card_renders() -> None:
    # No seeded signature (first-ever launch, nothing cached) -> render.
    assert _should_render(loading=False, current_sig=None, fresh_sig="y") is True
