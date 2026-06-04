"""Multi-segment chat rendering: a DeepSeek turn that interleaves assistant
text with tool calls must show each text segment as its own bubble, in flow
order, separated by the tool calls that followed it — not collapse them into
one bubble where the later segment overwrites the earlier one.

Runs headless via Qt's offscreen platform. To prove the *wiring* (not just the
``ChatPanel`` helper), events are driven through the real
``MainWindow._on_agent_event`` dispatch, which only touches ``_chat_panel`` —
so a lightweight stub stands in for the full window.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.core import AgentEvent  # noqa: E402
from src.tools.base import ToolResult  # noqa: E402
from src.ui.chat_panel import ChatPanel, InlineToolCall  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _WindowStub:
    """Minimal stand-in: ``_on_agent_event`` reads only ``self._chat_panel``."""

    def __init__(self, panel: ChatPanel) -> None:
        self._chat_panel = panel


def _drive(panel: ChatPanel, events: list[AgentEvent]) -> None:
    stub = _WindowStub(panel)
    for event in events:
        MainWindow._on_agent_event(stub, event)


def _flow(panel: ChatPanel) -> list[tuple[str, str]]:
    """Ordered ('bubble', text) / ('tool', name) entries in the message area."""
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


def _call(name: str) -> AgentEvent:
    return AgentEvent(kind="tool_call", payload={"id": name, "name": name, "arguments": {}})


def _ok(name: str, data: Any) -> AgentEvent:
    result = ToolResult(success=True, data=data)
    return AgentEvent(kind="tool_result", payload={"id": name, "name": name, "result": result})


def test_segments_split_into_distinct_bubbles_around_tool_call(app: QApplication) -> None:
    panel = ChatPanel()
    _drive(
        panel,
        [
            AgentEvent(kind="assistant_delta", payload={"text": "First "}),
            AgentEvent(kind="assistant_delta", payload={"text": "answer."}),
            AgentEvent(kind="llm_response", payload={"text": "First answer."}),
            _call("clock"),
            _ok("clock", {"now": "noon"}),
            AgentEvent(kind="assistant_delta", payload={"text": "Second "}),
            AgentEvent(kind="assistant_delta", payload={"text": "answer."}),
            AgentEvent(kind="llm_response", payload={"text": "Second answer."}),
            AgentEvent(kind="final", payload={"text": "Second answer."}),
        ],
    )

    flow = _flow(panel)
    kinds = [kind for kind, _ in flow]
    assert kinds == ["bubble", "tool", "bubble"], flow
    first, _tool, second = (text for _, text in flow)
    assert "First answer." in first and "Second" not in first
    assert "Second answer." in second and "First" not in second


def test_parallel_tool_calls_share_one_preceding_bubble(app: QApplication) -> None:
    panel = ChatPanel()
    _drive(
        panel,
        [
            AgentEvent(kind="assistant_delta", payload={"text": "Checking."}),
            AgentEvent(kind="llm_response", payload={"text": "Checking."}),
            _call("lecture"),
            _ok("lecture", {"items": []}),
            _call("clock"),
            _ok("clock", {"now": "noon"}),
            AgentEvent(kind="assistant_delta", payload={"text": "Done."}),
            AgentEvent(kind="llm_response", payload={"text": "Done."}),
            AgentEvent(kind="final", payload={"text": "Done."}),
        ],
    )

    flow = _flow(panel)
    assert [kind for kind, _ in flow] == ["bubble", "tool", "tool", "bubble"], flow
    assert "Checking." in flow[0][1]
    assert "Done." in flow[3][1]


def test_tool_only_iteration_creates_no_empty_bubble(app: QApplication) -> None:
    panel = ChatPanel()
    _drive(
        panel,
        [
            # First iteration emits a tool call with no prose (no deltas).
            AgentEvent(kind="llm_response", payload={"text": ""}),
            _call("clock"),
            _ok("clock", {"now": "noon"}),
            AgentEvent(kind="assistant_delta", payload={"text": "Here."}),
            AgentEvent(kind="llm_response", payload={"text": "Here."}),
            AgentEvent(kind="final", payload={"text": "Here."}),
        ],
    )

    flow = _flow(panel)
    assert [kind for kind, _ in flow] == ["tool", "bubble"], flow
    assert "Here." in flow[1][1]
