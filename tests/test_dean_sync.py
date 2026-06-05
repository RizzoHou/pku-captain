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

from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,  # noqa: E402
    QFrame,
    QLabel,
)

import src.ui.dashboard as dashboard  # noqa: E402
from src.tools.dean_updates import DeanInboxStore  # noqa: E402
from src.ui.formatters import (  # noqa: E402
    DEAN_CATEGORY_ORDER,
    group_dean_by_category,
)


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


def test_group_dean_by_category_canonical_order_and_empty_columns() -> None:
    items = [
        _item("notice:1", source="notice"),
        _item("rules:1", source="rules_school"),
        _item("notice:2", source="notice"),
    ]
    grouped = group_dean_by_category(items)
    # Every known category appears, in canonical order, even when empty.
    assert [src for src, _, _ in grouped] == [src for src, _ in DEAN_CATEGORY_ORDER]
    by_source = {src: col for src, _, col in grouped}
    assert [i["key"] for i in by_source["notice"]] == ["notice:1", "notice:2"]
    assert [i["key"] for i in by_source["rules_school"]] == ["rules:1"]
    assert by_source["download"] == []  # empty column kept, never dropped


def test_group_dean_by_category_appends_unknown_source() -> None:
    grouped = group_dean_by_category([_item("x:1", source="mystery")])
    sources = [src for src, _, _ in grouped]
    assert sources[: len(DEAN_CATEGORY_ORDER)] == [s for s, _ in DEAN_CATEGORY_ORDER]
    assert sources[-1] == "mystery"  # unknown source appended after the known set


def test_dean_messages_dialog_has_two_tabs_with_category_columns(
    app: QApplication,
) -> None:
    recent = [_item("notice:1", source="notice")]
    history = [_item("rules:9", source="rules_school")]
    dialog = dashboard.DeanMessagesDialog(recent, history, None)
    assert dialog._tabs.count() == 2
    assert dialog._tabs.tabText(0).startswith("新消息")
    assert dialog._tabs.tabText(1).startswith("历史消息")
    # The 新消息 tab lays out one column per category (canonical order).
    new_tab = dialog._tabs.widget(0)
    columns = [
        c for c in new_tab.findChildren(QFrame) if c.objectName() == "DeanColumn"
    ]
    assert len(columns) == len(DEAN_CATEGORY_ORDER)
    headers = [
        lbl.text()
        for lbl in new_tab.findChildren(QLabel)
        if lbl.objectName() == "DeanColumnHeader"
    ]
    assert "通知公告 · 1" in headers  # the one recent notice landed in its column
    assert "资料下载 · 0" in headers  # an empty category still renders a column
    dialog.deleteLater()
