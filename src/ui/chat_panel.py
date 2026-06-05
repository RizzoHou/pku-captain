"""Chat sidebar widgets for user input and assistant replies."""

from __future__ import annotations

import html
import re
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..llm.base import ChatMessage
from ..tools.base import ToolResult
from .tool_trace_panel import _format_tool_result, _to_json


class ChatPanel(QWidget):
    """Conversation panel that emits user messages and renders final replies."""

    send_requested = pyqtSignal(str)
    stop_requested = pyqtSignal()
    new_chat_requested = pyqtSignal()
    history_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ChatPanel")
        self.setMinimumWidth(520)
        self._streaming_bubble: QLabel | None = None
        self._streaming_text = ""
        self._tool_rows: dict[str, InlineToolCall] = {}
        # Chain-of-thought ("thinking") display, off by default. When off we
        # drop reasoning_delta events outright rather than building hidden
        # widgets — a max-effort CoT can be very long.
        self._show_thinking = False
        self._streaming_thinking: InlineThinking | None = None
        self._thinking_rows: list[InlineThinking] = []

        self._message_layout = QVBoxLayout()
        self._message_layout.setSpacing(10)
        self._message_layout.addStretch()

        message_host = QWidget()
        message_host.setObjectName("MessageHost")
        message_host.setLayout(self._message_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("MessageScroll")
        scroll.setWidget(message_host)
        self._scroll = scroll

        self._input = MessageInput()
        self._input.setPlaceholderText("问问 PKU Captain...")
        self._input.setFixedHeight(82)
        self._input.send_requested.connect(self._emit_send)

        self._send_button = QPushButton("发送")
        self._send_button.setObjectName("PrimaryButton")
        self._send_button.setDefault(True)
        self._send_button.clicked.connect(self._emit_send)

        # Shares the send button's slot in the input row: hidden while idle,
        # shown (and the send button hidden) while a turn runs, so one click
        # can stop a long-running answer. See `set_busy`.
        self._stop_button = QPushButton("■ 停止")
        self._stop_button.setObjectName("StopButton")
        self._stop_button.setToolTip("停止当前正在生成的回答")
        self._stop_button.hide()
        self._stop_button.clicked.connect(self._emit_stop)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_button)
        input_row.addWidget(self._stop_button)

        title = QLabel("对话")
        title.setObjectName("SectionTitle")
        self._thinking_toggle = QPushButton("💭 思考可见")
        self._thinking_toggle.setObjectName("ThinkingToggleButton")
        self._thinking_toggle.setCheckable(True)
        self._thinking_toggle.setChecked(False)
        self._thinking_toggle.setProperty("thinkingVisible", False)
        self._thinking_toggle.setToolTip("显示 / 隐藏模型的思考过程（默认隐藏）")
        self._thinking_toggle.toggled.connect(self._on_thinking_toggled)
        self._new_chat_button = QPushButton("＋ 新对话")
        self._new_chat_button.setObjectName("SecondaryButton")
        self._new_chat_button.clicked.connect(lambda: self.new_chat_requested.emit())
        self._history_button = QPushButton("历史会话")
        self._history_button.setObjectName("SecondaryButton")
        self._history_button.clicked.connect(lambda: self.history_requested.emit())

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(self._thinking_toggle)
        header_row.addWidget(self._new_chat_button)
        header_row.addWidget(self._history_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(header_row)
        layout.addWidget(scroll, 1)
        layout.addLayout(input_row)

    def set_busy(self, busy: bool) -> None:
        """Disable input while a turn is running.

        Swaps the send button for the stop button in the same slot so the
        primary action while busy is "停止". `set_busy(False)` also re-arms the
        stop button (a prior cancel click disabled it for feedback).
        """
        self._input.setEnabled(not busy)
        self._send_button.setVisible(not busy)
        self._stop_button.setVisible(busy)
        if not busy:
            self._stop_button.setEnabled(True)
            self._stop_button.setText("■ 停止")
        # Block session switching mid-turn so the conversation isn't swapped
        # while the worker thread is still appending to it.
        self._new_chat_button.setEnabled(not busy)
        self._history_button.setEnabled(not busy)

    def mark_stopping(self) -> None:
        """Give immediate feedback that a stop click registered.

        Cancellation is cooperative — an in-flight tool or LLM call can't be
        interrupted, so there may be a short delay before the turn ends. Disable
        the button and relabel it so the click visibly took effect.
        """
        self._stop_button.setEnabled(False)
        self._stop_button.setText("停止中…")

    def add_user_message(self, text: str) -> None:
        self._add_message("你", text, "user")

    def add_assistant_message(self, text: str) -> None:
        # The visible answer means this segment's thinking is complete.
        self._finish_thinking()
        if self._streaming_bubble is not None:
            self._streaming_text = text or self._streaming_text or "（空回复）"
            self._streaming_bubble.setText(
                _message_html(self._streaming_text, "assistant")
            )
            self._streaming_bubble = None
            self._streaming_text = ""
            self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())
            return
        self._add_message("PKU Captain", text or "（空回复）", "assistant")

    def append_assistant_delta(self, text: str) -> None:
        if not text:
            return
        # First answer token: the model has stopped thinking for this segment.
        self._finish_thinking()
        if self._streaming_bubble is None:
            self._streaming_text = ""
            self._streaming_bubble = self._add_message(
                "PKU Captain",
                "正在生成...",
                "assistant",
            )
        self._streaming_text += text
        self._streaming_bubble.setText(
            _message_html(self._streaming_text, "assistant")
        )
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

    def append_reasoning_delta(self, text: str) -> None:
        """Stream a chain-of-thought token into the current thinking window.

        No-op when the thinking toggle is off — we deliberately don't build
        hidden widgets for a long CoT. When on, the first delta of a segment
        creates an `InlineThinking` window above the answer bubble; later
        deltas append to it.
        """
        if not text or not self._show_thinking:
            return
        if self._streaming_thinking is None:
            # Collapse earlier segments' thinking so a multi-tool turn keeps
            # only the active window open — bounding the *stack* of windows the
            # same way each window bounds its own height. A single-answer turn
            # never triggers this, so its thinking stays open while read.
            for row in self._thinking_rows:
                row.collapse()
            self._streaming_thinking = InlineThinking()
            self._thinking_rows.append(self._streaming_thinking)
            self._insert_flow_widget(self._streaming_thinking)
        self._streaming_thinking.append(text)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

    def set_show_thinking(self, show: bool) -> None:
        """Toggle thinking visibility (also reflected on the header button)."""
        if self._thinking_toggle.isChecked() != show:
            self._thinking_toggle.setChecked(show)
        else:
            self._on_thinking_toggled(show)

    def _on_thinking_toggled(self, checked: bool) -> None:
        self._show_thinking = checked
        # Action label: when hidden, the button offers to reveal ("思考可见");
        # when shown, it offers to hide ("思考不可见").
        self._thinking_toggle.setText("💭 思考不可见" if checked else "💭 思考可见")
        self._thinking_toggle.setProperty("thinkingVisible", checked)
        self._thinking_toggle.style().unpolish(self._thinking_toggle)
        self._thinking_toggle.style().polish(self._thinking_toggle)
        # Hide/reveal already-rendered windows so the toggle affects the
        # current view, not just future segments. Reasoning that arrived while
        # off was dropped and can't be recovered.
        for row in self._thinking_rows:
            row.setVisible(checked)

    def _finish_thinking(self) -> None:
        """Lock in the in-progress thinking window (stop auto-follow, retitle)."""
        if self._streaming_thinking is not None:
            self._streaming_thinking.mark_done()
            self._streaming_thinking = None

    def _add_finalized_thinking(self, text: str) -> None:
        """Render a complete (non-streaming) thinking window, e.g. on history
        load, where the full `reasoning_content` is already known."""
        row = InlineThinking()
        row.set_text(text)
        row.mark_done()
        row.collapse()  # restored reasoning is past context — keep it compact
        self._thinking_rows.append(row)
        self._insert_flow_widget(row)

    def reset_streaming(self) -> None:
        """Finalize an in-progress streaming bubble (e.g. after a turn error).

        A turn that ends via an error emits no ``final`` event, so the
        streaming bubble would otherwise persist and the next turn's first
        delta would append onto its stale text. Finalize it in place,
        keeping whatever partial text arrived, and clear the state.
        """
        self._finalize_streaming("（回复中断）")

    def finalize_assistant_segment(self) -> None:
        """Lock in the current streaming bubble as one complete segment.

        A single agent turn can interleave assistant text with tool calls
        (text → tool call → more text → ...), one segment per LLM iteration.
        Each text run must be its own bubble; call this before rendering a
        tool call so the current run is finalized and the next run starts a
        fresh bubble *below* the tool rows. Without it, later segments would
        overwrite the first bubble (the cause of a later message replacing
        an earlier one, displayed above its tool calls instead of below).
        """
        self._finalize_streaming("（空回复）")

    def _finalize_streaming(self, empty_fallback: str) -> None:
        # Lock in the thinking window first so it sits above the tool row a
        # tool-only iteration is about to render (no answer token will arrive
        # to finalize it otherwise).
        self._finish_thinking()
        if self._streaming_bubble is None:
            return
        self._streaming_bubble.setText(
            _message_html(self._streaming_text or empty_fallback, "assistant")
        )
        self._streaming_bubble = None
        self._streaming_text = ""

    def add_system_message(self, text: str) -> None:
        self._add_message("系统", text, "system")

    def add_tool_call(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        row = InlineToolCall()
        row.set_trace(name, "调用中", _to_json(arguments), "pending")
        self._tool_rows[call_id] = row
        self._insert_flow_widget(row)

    def update_tool_result(self, call_id: str, name: str, result: Any) -> None:
        row = self._tool_rows.get(call_id)
        if row is None:
            row = InlineToolCall()
            self._tool_rows[call_id] = row
            self._insert_flow_widget(row)

        success = bool(getattr(result, "success", False))
        body = getattr(result, "data", None) if success else getattr(result, "error", None)
        status = "完成" if success else "失败"
        role = "success" if success else "error"
        row.set_trace(name, status, _format_tool_result(name, body), role)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

    def clear(self) -> None:
        """Remove every message and reset streaming/tool state.

        Used when starting a new chat or loading a saved one. Keeps the
        trailing stretch (always the last layout item) so new messages still
        flow from the top.
        """
        while self._message_layout.count() > 1:
            item = self._message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._streaming_bubble = None
        self._streaming_text = ""
        self._tool_rows = {}
        self._streaming_thinking = None
        self._thinking_rows = []

    def load_history(self, messages: list[ChatMessage]) -> None:
        """Re-render a saved conversation, reproducing the live flow order.

        The persisted flat message list already interleaves correctly
        (assistant-segment → its tool calls → tool results → next segment),
        so a single in-order pass reproduces what the event stream rendered.
        An assistant message that only made tool calls has empty content and
        must render no bubble (matching the live path). Tool messages are
        plain strings; reconstruct a `ToolResult` from the `ERROR: ` prefix
        convention `Agent` writes (`str(result.data)` vs `f"ERROR: {error}"`).
        """
        self.clear()
        for msg in messages:
            if msg.role == "user":
                self.add_user_message(msg.content)
            elif msg.role == "assistant":
                # Thinking precedes the answer in live flow; replay it first.
                if self._show_thinking and msg.reasoning_content:
                    self._add_finalized_thinking(msg.reasoning_content)
                if msg.content.strip():
                    self.add_assistant_message(msg.content)
                for call in msg.tool_calls:
                    self.add_tool_call(call.id, call.name, dict(call.arguments))
            elif msg.role == "tool":
                self.update_tool_result(
                    msg.tool_call_id or "",
                    msg.name or "",
                    _tool_result_from_content(msg.content),
                )
            # system messages are not rendered

    def _emit_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.send_requested.emit(text)

    def _emit_stop(self) -> None:
        self.mark_stopping()
        self.stop_requested.emit()

    def _add_message(self, author: str, text: str, role: str) -> QLabel:
        bubble = QFrame()
        bubble.setObjectName("MessageBubble")
        bubble.setProperty("messageRole", role)
        bubble.setMaximumWidth(720 if role == "assistant" else 440)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        author_label = QLabel(author)
        author_label.setObjectName("MessageAuthor")

        body_label = QLabel()
        body_label.setObjectName("MessageText")
        body_label.setTextFormat(body_label.textFormat().RichText)
        body_label.setWordWrap(True)
        body_label.setOpenExternalLinks(True)
        body_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_label.setText(_message_html(text, role))

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(10, 8, 10, 8)
        bubble_layout.setSpacing(4)
        bubble_layout.addWidget(author_label)
        bubble_layout.addWidget(body_label)

        row = QHBoxLayout()
        if role == "user":
            row.addStretch()
            row.addWidget(bubble, 0)
        else:
            row.addWidget(bubble, 0)
            row.addStretch()

        row_host = QWidget()
        row_host.setLayout(row)
        self._insert_flow_widget(row_host)
        return body_label

    def _insert_flow_widget(self, widget: QWidget) -> None:
        self._message_layout.insertWidget(self._message_layout.count() - 1, widget)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())


def _tool_result_from_content(content: str) -> ToolResult:
    """Rebuild a `ToolResult` from a persisted `tool` message string.

    `Agent` stores `str(result.data)` on success and `f"ERROR: {error}"` on
    failure, so the prefix is the only signal of which it was. Structured
    `data` is not recoverable (only its string form was saved) — replayed
    tool rows therefore show the stringified blob; see the v1 limitation note.
    """
    if content.startswith("ERROR: "):
        return ToolResult(success=False, error=content[len("ERROR: ") :])
    return ToolResult(success=True, data=content)


class InlineToolCall(QFrame):
    """Compact tool-call record shown inside the chat flow."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("InlineToolCall")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMaximumWidth(720)
        self._expanded = False

        self._name_label = QLabel("")
        self._name_label.setObjectName("InlineToolName")
        self._name_label.setWordWrap(True)
        self._status_label = QLabel("")
        self._status_label.setObjectName("InlineToolStatus")

        self._toggle_button = QPushButton("展开")
        self._toggle_button.setObjectName("InlineToggleButton")
        self._toggle_button.clicked.connect(self._toggle_detail)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self._name_label, 1)
        header.addWidget(self._status_label, 0)
        header.addWidget(self._toggle_button, 0)

        self._detail_label = QLabel("")
        self._detail_label.setObjectName("InlineToolDetail")
        self._detail_label.setTextInteractionFlags(
            self._detail_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail_label.setWordWrap(True)
        self._detail_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._detail_label)

    def set_trace(self, name: str, status: str, detail: str, role: str) -> None:
        self.setProperty("traceRole", role)
        self.style().unpolish(self)
        self.style().polish(self)
        self._name_label.setText(f"工具 · {name}")
        self._status_label.setText(status)
        self._detail_label.setText(detail)
        self._apply_expanded()

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    def _apply_expanded(self) -> None:
        self._detail_label.setVisible(self._expanded)
        self._toggle_button.setText("收起" if self._expanded else "展开")


class InlineThinking(QFrame):
    """Bounded, auto-scrolling view of the model's chain-of-thought.

    The body is a read-only, fixed-max-height text box. As reasoning streams
    in it auto-scrolls to the bottom — a sliding window that shows the latest
    thinking while a long chain-of-thought stays capped instead of flooding
    the chat. Streaming uses ``insertPlainText`` (O(delta), not O(total)) so
    a very long CoT renders cheaply. The header toggle collapses the body.
    """

    _MAX_HEIGHT = 160
    _MAX_WIDTH = 720
    _FRAME_PADDING = 24
    _TEXT_PADDING = 10

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("InlineThinking")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setMaximumWidth(self._MAX_WIDTH)
        self._expanded = True
        self._follow = True  # auto-scroll to newest while streaming
        self._wrap_width = self._MAX_WIDTH - self._FRAME_PADDING - self._TEXT_PADDING
        self._saturated = False  # both size caps hit -> skip per-delta re-measure

        self._title_label = QLabel("💭 思考中…")
        self._title_label.setObjectName("InlineThinkingTitle")
        self._toggle_button = QPushButton("收起")
        self._toggle_button.setObjectName("InlineToggleButton")
        self._toggle_button.clicked.connect(self._toggle_detail)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(self._title_label, 1)
        header.addWidget(self._toggle_button, 0)

        self._body = QPlainTextEdit()
        self._body.setObjectName("InlineThinkingBody")
        self._body.setReadOnly(True)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body.setMaximumHeight(self._MAX_HEIGHT)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._sync_height_to_text()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._body)

    def append(self, text: str) -> None:
        self._body.moveCursor(QTextCursor.MoveOperation.End)
        self._body.insertPlainText(text)
        # Both size syncs scan the full text (O(total)); appended text only ever
        # grows the box, so once it saturates both caps further deltas can't
        # change its size — skip the scan and keep streaming O(delta), the way a
        # huge max-effort CoT renders cheaply.
        if not self._saturated:
            self._sync_size_to_text()
        # Cursor sits at the new end; ensureCursorVisible pins the window to the
        # newest thinking without depending on a (possibly stale) scrollbar max.
        if self._follow:
            self._body.ensureCursorVisible()

    def set_text(self, text: str) -> None:
        """Replace the whole body (history load — full text known up front)."""
        self._body.setPlainText(text)
        self._saturated = False  # replacement can shrink — always re-measure
        self._sync_size_to_text()

    def _sync_size_to_text(self) -> None:
        # Force the QSS font (`#InlineThinkingBody { font-size: 11px }`) to
        # resolve synchronously before measuring. Qt applies a stylesheet font
        # only at polish time, which for the first thinking window of a session
        # lands *after* the streaming burst that sized it — so the box was
        # measured against the larger default font and kept a too-tall height
        # that no later delta corrected. ensurePolished() is a cheap flag-check
        # once polished, so the streaming path stays O(delta).
        self._body.ensurePolished()
        self._sync_width_to_text()
        self._sync_height_to_text()
        self._saturated = (
            self.maximumWidth() == self._MAX_WIDTH
            and self._body.maximumHeight() == self._MAX_HEIGHT
        )

    def mark_done(self) -> None:
        """Stop auto-following and retitle once the segment's CoT is complete."""
        self._follow = False
        self._title_label.setText("💭 思考过程")

    def collapse(self) -> None:
        """Hide the body, leaving a one-line '思考过程 [展开]' header."""
        self._expanded = False
        self._body.setVisible(False)
        self._toggle_button.setText("展开")

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_button.setText("收起" if self._expanded else "展开")

    def _sync_width_to_text(self) -> None:
        """Shrink the thinking window to short text, capped at the max width."""
        text = self._body.toPlainText()
        metrics = QFontMetrics(self._body.font())
        widest = max((metrics.horizontalAdvance(line) for line in text.splitlines()), default=0)
        content_width = widest + self._TEXT_PADDING
        header_width = (
            QFontMetrics(self._title_label.font()).horizontalAdvance(self._title_label.text())
            + QFontMetrics(self._toggle_button.font()).horizontalAdvance(self._toggle_button.text())
            + 64
        )
        width = min(self._MAX_WIDTH, max(content_width, header_width) + self._FRAME_PADDING)
        self.setFixedWidth(width)
        # Text wraps at the body's inner width (frame minus its horizontal
        # chrome). Stash it so height-sync can count wrapped lines synchronously,
        # without waiting for the body's deferred resize to settle.
        self._wrap_width = max(1, width - self._FRAME_PADDING - self._TEXT_PADDING)

    def _sync_height_to_text(self) -> None:
        """Grow the thinking window to fit its text, capped at the max height.

        QPlainTextEdit lays out lazily off its (deferred) viewport width, so its
        own document line count is stale right after a width change — and
        ``QPlainTextDocumentLayout`` ignores ``setTextWidth``, so we can't force
        it either. Instead we count wrapped lines directly from font metrics at
        the known wrap width: synchronous, and correct even for a long single
        paragraph (which wraps to many visual lines, not one). Short reasoning
        shrinks the box; long reasoning saturates at the cap and the
        sliding-window auto-follow takes over.
        """
        metrics = QFontMetrics(self._body.font())
        # Reserve the vertical scrollbar width: once the box is tall enough to
        # scroll, the bar eats that much of the text area, so wrap must assume it.
        scrollbar = self._body.verticalScrollBar().sizeHint().width()
        wrap = max(1, self._wrap_width - scrollbar)
        lines = sum(
            max(1, -(-metrics.horizontalAdvance(line) // wrap))  # ceil(advance / wrap)
            for line in self._body.toPlainText().split("\n")
        )
        chrome = round(2 * self._body.document().documentMargin()) + 4
        height = min(self._MAX_HEIGHT, lines * metrics.lineSpacing() + chrome)
        self._body.setFixedHeight(height)


def _message_html(text: str, role: str) -> str:
    body = _render_message_body(text, role)
    return body


def _render_message_body(text: str, role: str) -> str:
    if role != "assistant":
        return html.escape(text).replace("\n", "<br>")

    blocks = re.split(r"(```.*?```)", text, flags=re.DOTALL)
    rendered: list[str] = []
    for block in blocks:
        if block.startswith("```") and block.endswith("```"):
            code = block.strip("`")
            lines = code.splitlines()
            if lines and lines[0].strip().isalpha():
                lines = lines[1:]
            rendered.append(
                "<pre style='white-space: pre-wrap; background: #fffaf7; "
                "border: 1px solid #eadbd5; border-radius: 6px; "
                "padding: 8px; margin: 7px 0;'>"
                f"{html.escape(chr(10).join(lines)).strip()}</pre>"
            )
        else:
            rendered.append(_render_markdownish_text(block))
    return "".join(rendered) or "（空回复）"


def _render_markdownish_text(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_list = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<br>")
            index += 1
            continue
        if _is_table_start(lines, index):
            if in_list:
                out.append("</ul>")
                in_list = False
            table_lines = [stripped, lines[index + 1].strip()]
            index += 2
            while index < len(lines) and _looks_like_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            out.append(_table_html(table_lines))
            continue
        if stripped in {"---", "***", "___"}:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(
                "<div style='border-top: 1px solid #eadbd5; "
                "margin: 10px 0; height: 1px;'></div>"
            )
            index += 1
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul style='margin: 4px 0 4px 18px; padding: 0;'>")
                in_list = True
            out.append(f"<li>{_inline_markdown(stripped[2:])}</li>")
            index += 1
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            out.append(_heading_html(stripped[4:], weight=700))
        elif stripped.startswith("## "):
            out.append(_heading_html(stripped[3:], weight=800))
        elif stripped.startswith("# "):
            out.append(_heading_html(stripped[2:], weight=800))
        else:
            out.append(f"<div style='margin: 3px 0;'>{_inline_markdown(stripped)}</div>")
        index += 1
    if in_list:
        out.append("</ul>")
    return "".join(out)


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(
        r"`([^`]+)`",
        r"<code style='background: #fffaf7; padding: 1px 4px; border-radius: 4px;'>\1</code>",
        escaped,
    )
    return escaped


def _heading_html(text: str, *, weight: int) -> str:
    return (
        f"<div style='font-weight: {weight}; margin-top: 8px;'>"
        f"{_inline_markdown(text)}</div>"
    )


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return (
        _looks_like_table_row(lines[index].strip())
        and _looks_like_table_separator(lines[index + 1].strip())
    )


def _looks_like_table_row(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _looks_like_table_separator(line: str) -> bool:
    if not _looks_like_table_row(line):
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_html(lines: list[str]) -> str:
    headers = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    column_count = max([len(headers), *(len(row) for row in rows)] or [0])
    if column_count == 0:
        return ""

    header_cells = "".join(
        "<th style='background: #fff6ed; color: #650000; "
        "font-weight: 700; padding: 5px 7px; border: 1px solid #eadbd5;'>"
        f"{_inline_markdown(_cell_at(headers, column))}</th>"
        for column in range(column_count)
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            "<td style='padding: 5px 7px; border: 1px solid #eadbd5;'>"
            f"{_inline_markdown(_cell_at(row, column))}</td>"
            for column in range(column_count)
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        "<table cellspacing='0' cellpadding='0' "
        "style='border-collapse: collapse; margin: 8px 0;'>"
        f"<tr>{header_cells}</tr>{''.join(body_rows)}</table>"
    )


def _cell_at(cells: list[str], index: int) -> str:
    return cells[index] if index < len(cells) else ""


class MessageInput(QPlainTextEdit):
    """Input box where Enter sends and Shift+Enter inserts a newline."""

    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override name.
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)
