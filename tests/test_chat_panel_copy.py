"""Assistant chat output is selectable/copyable (drag-select + right-click Copy)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.ui.chat_panel import ChatPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _assistant_body(panel: ChatPanel) -> QLabel:
    labels = panel.findChildren(QLabel, "MessageText")
    assert labels, "no message body QLabel found"
    return labels[-1]


def test_finalized_assistant_body_is_selectable(app: QApplication) -> None:
    panel = ChatPanel()
    panel.add_assistant_message("你好，这是一个可以复制的回答。")
    QApplication.processEvents()

    body = _assistant_body(panel)
    flags = body.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
    # The rendered body still carries the answer text.
    assert "可以复制" in body.text()


def test_streaming_assistant_body_is_selectable(app: QApplication) -> None:
    panel = ChatPanel()
    panel.append_assistant_delta("流式")
    panel.append_assistant_delta("输出")
    QApplication.processEvents()

    body = _assistant_body(panel)
    flags = body.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_user_body_is_selectable(app: QApplication) -> None:
    panel = ChatPanel()
    panel.add_user_message("用户也想复制自己的话")
    QApplication.processEvents()

    body = _assistant_body(panel)
    flags = body.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_selectable_body_keeps_links_active(app: QApplication) -> None:
    # TextSelectableByMouse must not strip link interaction: LinksAccessibleByMouse
    # stays set so anchors remain clickable alongside drag-select.
    panel = ChatPanel()
    panel.add_assistant_message("见 [官网](https://example.com)")
    QApplication.processEvents()

    body = _assistant_body(panel)
    flags = body.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.LinksAccessibleByMouse
