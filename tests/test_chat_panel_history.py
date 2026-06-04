"""ChatPanel.load_history: replaying a saved conversation reproduces the live
flow — a tool-only assistant message renders no empty bubble, tool rows
reconstruct their success/error status, and a prior conversation is cleared.

Runs headless via Qt's offscreen platform (mirrors test_chat_panel_segments)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.llm.base import ChatMessage, ToolCall  # noqa: E402
from src.ui.chat_panel import ChatPanel, InlineToolCall  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _flow(panel: ChatPanel) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    layout = panel._message_layout
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None:  # trailing stretch
            continue
        if isinstance(widget, InlineToolCall):
            entries.append(("tool", widget._name_label.text()))
            continue
        label = widget.findChild(QLabel, "MessageText")
        if label is not None:
            entries.append(("bubble", label.text()))
    return entries


def _tool_rows(panel: ChatPanel) -> list[InlineToolCall]:
    layout = panel._message_layout
    return [
        widget
        for index in range(layout.count())
        if isinstance((widget := layout.itemAt(index).widget()), InlineToolCall)
    ]


def _history() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="现在几点"),
        ChatMessage(
            role="assistant",
            content="",  # tool-only iteration — must render no bubble
            tool_calls=(ToolCall(id="c1", name="clock", arguments={}),),
        ),
        ChatMessage(role="tool", name="clock", tool_call_id="c1", content="noon"),
        ChatMessage(role="assistant", content="现在中午十二点"),
    ]


def test_load_history_reproduces_flow(app: QApplication) -> None:
    panel = ChatPanel()
    panel.load_history(_history())

    flow = _flow(panel)
    assert [kind for kind, _ in flow] == ["bubble", "tool", "bubble"], flow
    assert "现在几点" in flow[0][1]
    assert "现在中午十二点" in flow[2][1]
    assert _tool_rows(panel)[0]._status_label.text() == "完成"


def test_load_history_clears_previous(app: QApplication) -> None:
    panel = ChatPanel()
    panel.add_user_message("旧的消息应当被清掉")
    panel.load_history(_history())
    assert all("旧的消息" not in text for _, text in _flow(panel))


def test_load_history_reconstructs_error_tool_row(app: QApplication) -> None:
    panel = ChatPanel()
    panel.load_history(
        [
            ChatMessage(role="user", content="跑个工具"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=(ToolCall(id="c1", name="thing", arguments={}),),
            ),
            ChatMessage(role="tool", name="thing", tool_call_id="c1", content="ERROR: boom"),
        ]
    )
    assert _tool_rows(panel)[0]._status_label.text() == "失败"
