"""Dashboard-side coverage for the DEAN card (headless/offscreen).

Pins two behaviors:
  * the empty state is a single line (the summary), with no duplicate label, and
  * the card accumulates poll snapshots into the inbox so an item never vanishes
    on the next (empty) poll — the recency window, not the latest poll, drives
    what the card shows.
No agent, QThread, or network is involved.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import src.ui.dashboard as dashboard  # noqa: E402
from src.tools.dean_updates import DeanInboxStore  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _panel() -> dashboard.DashboardPanel:
    return dashboard.DashboardPanel(
        mode_label="在线模式", tools=None, dean_inbox=DeanInboxStore()
    )


def _item(key, *, source="notice", item_id="1", date=""):
    return {
        "key": key,
        "source": source,
        "source_label": "通知公告",
        "title": key,
        "url": "u",
        "date": date,
        "item_id": item_id,
    }


def _widget_count(layout) -> int:  # noqa: ANN001
    return sum(1 for i in range(layout.count()) if layout.itemAt(i).widget() is not None)


def test_dean_card_empty_state_is_single_line(app: QApplication) -> None:
    panel = _panel()
    panel.set_dean_updates({"items": []})
    card = panel._cards["dean_updates"]
    assert card._summary_label.text() == "暂无教务部内容"
    # The fix: no duplicate empty QLabel in the list area.
    assert _widget_count(card._list_layout) == 0


def test_dean_card_keeps_item_after_empty_poll(app: QApplication) -> None:
    panel = _panel()
    panel.set_dean_updates({"items": [_item("notice:1")]})
    assert [e["key"] for e in panel._dean_inbox.entries()] == ["notice:1"]

    # An empty poll (the common next tick) must NOT drop the accumulated item.
    panel.set_dean_updates({"items": []})
    assert [e["key"] for e in panel._dean_inbox.entries()] == ["notice:1"]


def test_dean_card_accumulates_across_polls(app: QApplication) -> None:
    panel = _panel()
    panel.set_dean_updates({"items": [_item("notice:1", item_id="1")]})
    panel.set_dean_updates({"items": [_item("notice:2", item_id="2")]})
    keys = {e["key"] for e in panel._dean_inbox.entries()}
    assert keys == {"notice:1", "notice:2"}
