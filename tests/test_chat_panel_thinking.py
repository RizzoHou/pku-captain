"""Thinking-chunk visibility: the chain-of-thought ("thinking") stream is
hidden by default and, when toggled on, renders in a bounded sliding-window
widget that sits above the answer/tool row of its segment.

Events are driven through the real ``MainWindow._on_agent_event`` dispatch
(same pattern as test_chat_panel_segments) so the wiring is covered, not just
the ``ChatPanel`` helpers. Runs headless via Qt's offscreen platform.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.core import AgentEvent  # noqa: E402
from src.llm.base import ChatMessage  # noqa: E402
from src.tools.base import ToolResult  # noqa: E402
from src.ui.chat_panel import ChatPanel, InlineThinking, InlineToolCall  # noqa: E402
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
    """Ordered flow entries: ('thinking', text) / ('bubble', text) / ('tool', name)."""
    entries: list[tuple[str, str]] = []
    layout = panel._message_layout
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None:  # trailing stretch
            continue
        if isinstance(widget, InlineThinking):
            entries.append(("thinking", widget._body.toPlainText()))
            continue
        if isinstance(widget, InlineToolCall):
            entries.append(("tool", widget._name_label.text()))
            continue
        label = widget.findChild(QLabel, "MessageText")
        if label is not None:
            entries.append(("bubble", label.text()))
    return entries


def _thinking_rows(panel: ChatPanel) -> list[InlineThinking]:
    layout = panel._message_layout
    return [
        widget
        for index in range(layout.count())
        if isinstance((widget := layout.itemAt(index).widget()), InlineThinking)
    ]


def _reason(text: str) -> AgentEvent:
    return AgentEvent(kind="reasoning_delta", payload={"text": text})


def _delta(text: str) -> AgentEvent:
    return AgentEvent(kind="assistant_delta", payload={"text": text})


def _call(name: str) -> AgentEvent:
    return AgentEvent(kind="tool_call", payload={"id": name, "name": name, "arguments": {}})


def _ok(name: str, data: object) -> AgentEvent:
    result = ToolResult(success=True, data=data)
    return AgentEvent(kind="tool_result", payload={"id": name, "name": name, "result": result})


def test_thinking_hidden_by_default(app: QApplication) -> None:
    panel = ChatPanel()
    assert panel._thinking_toggle.isChecked() is False
    _drive(
        panel,
        [
            _reason("let me think about this"),
            _delta("The answer."),
            AgentEvent(kind="llm_response", payload={"text": "The answer."}),
            AgentEvent(kind="final", payload={"text": "The answer."}),
        ],
    )
    # Reasoning dropped outright — no thinking widget built when off.
    assert _thinking_rows(panel) == []
    assert [kind for kind, _ in _flow(panel)] == ["bubble"]


def test_thinking_shown_above_answer_when_on(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_show_thinking(True)
    _drive(
        panel,
        [
            _reason("first I consider X, "),
            _reason("then Y"),
            _delta("Final answer."),
            AgentEvent(kind="llm_response", payload={"text": "Final answer."}),
            AgentEvent(kind="final", payload={"text": "Final answer."}),
        ],
    )
    flow = _flow(panel)
    assert [kind for kind, _ in flow] == ["thinking", "bubble"], flow
    assert flow[0][1] == "first I consider X, then Y"
    assert "Final answer." in flow[1][1]
    # Completed segment retitles away from the live "思考中" state.
    assert _thinking_rows(panel)[0]._title_label.text() == "💭 思考过程"


def test_thinking_finalized_before_tool_only_iteration(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_show_thinking(True)
    _drive(
        panel,
        [
            # Tool-only iteration: reasoning, then a tool call with no prose.
            _reason("I should check the clock"),
            AgentEvent(kind="llm_response", payload={"text": ""}),
            _call("clock"),
            _ok("clock", {"now": "noon"}),
            _reason("now I can answer"),
            _delta("It is noon."),
            AgentEvent(kind="llm_response", payload={"text": "It is noon."}),
            AgentEvent(kind="final", payload={"text": "It is noon."}),
        ],
    )
    flow = _flow(panel)
    # Each segment's thinking locks in above its tool row / answer bubble.
    assert [kind for kind, _ in flow] == ["thinking", "tool", "thinking", "bubble"], flow
    assert flow[0][1] == "I should check the clock"
    assert flow[2][1] == "now I can answer"


def test_earlier_thinking_collapses_when_next_segment_starts(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_show_thinking(True)
    _drive(
        panel,
        [
            _reason("segment one reasoning"),
            AgentEvent(kind="llm_response", payload={"text": ""}),
            _call("clock"),
            _ok("clock", {"now": "noon"}),
            _reason("segment two reasoning"),  # new segment -> collapse the first
            _delta("It is noon."),
            AgentEvent(kind="final", payload={"text": "It is noon."}),
        ],
    )
    rows = _thinking_rows(panel)
    assert len(rows) == 2
    # Only the active (last) window stays open; the earlier one collapses so a
    # multi-tool turn doesn't stack full-height thinking windows.
    assert rows[0]._expanded is False
    assert rows[1]._expanded is True


def test_toggle_hides_and_reveals_existing_windows(app: QApplication) -> None:
    panel = ChatPanel()
    assert panel._thinking_toggle.property("thinkingVisible") is False
    panel._thinking_toggle.setChecked(True)  # exercise the real GUI entry point
    assert panel._thinking_toggle.property("thinkingVisible") is True
    _drive(
        panel,
        [
            _reason("thinking out loud"),
            _delta("Done."),
            AgentEvent(kind="final", payload={"text": "Done."}),
        ],
    )
    row = _thinking_rows(panel)[0]
    assert row.isHidden() is False
    panel._thinking_toggle.setChecked(False)
    assert panel._thinking_toggle.property("thinkingVisible") is False
    assert row.isHidden() is True
    panel._thinking_toggle.setChecked(True)
    assert panel._thinking_toggle.property("thinkingVisible") is True
    assert row.isHidden() is False


def test_thinking_window_shrinks_for_short_text_and_caps_long_text(app: QApplication) -> None:
    short = InlineThinking()
    short.append("tiny")

    long = InlineThinking()
    long.append("x" * 2000)

    assert short.width() < InlineThinking._MAX_WIDTH
    assert long.width() == InlineThinking._MAX_WIDTH


def test_thinking_window_height_grows_with_text_and_caps(app: QApplication) -> None:
    # Height is driven via setFixedHeight, so the body's fixed height tracks the
    # text length deterministically (no show()/event-loop needed).
    one_line = InlineThinking()
    one_line.append("tiny")

    five_lines = InlineThinking()
    five_lines.set_text("\n".join(f"line {i}" for i in range(5)))

    # A long single paragraph (no newlines) still wraps to many visual lines.
    long_para = InlineThinking()
    long_para.set_text("这是一段很长的思考内容，" * 80)

    assert one_line._body.maximumHeight() < five_lines._body.maximumHeight()
    assert five_lines._body.maximumHeight() < InlineThinking._MAX_HEIGHT
    assert long_para._body.maximumHeight() == InlineThinking._MAX_HEIGHT


def test_thinking_toggle_text_reflects_visibility(app: QApplication) -> None:
    panel = ChatPanel()
    assert panel._thinking_toggle.text() == "💭 思考可见"
    panel._thinking_toggle.setChecked(True)
    assert panel._thinking_toggle.text() == "💭 思考不可见"
    panel._thinking_toggle.setChecked(False)
    assert panel._thinking_toggle.text() == "💭 思考可见"


def test_history_replays_thinking_only_when_on(app: QApplication) -> None:
    history = [
        ChatMessage(role="user", content="现在几点"),
        ChatMessage(
            role="assistant",
            content="现在中午十二点",
            reasoning_content="用户问时间，我应当直接回答",
        ),
    ]

    off = ChatPanel()
    off.load_history(history)
    assert _thinking_rows(off) == []

    on = ChatPanel()
    on.set_show_thinking(True)
    on.load_history(history)
    flow = _flow(on)
    assert [kind for kind, _ in flow] == ["bubble", "thinking", "bubble"], flow
    assert "用户问时间" in flow[1][1]
