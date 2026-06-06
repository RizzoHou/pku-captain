"""Chat sidebar widgets for user input and assistant replies."""

from __future__ import annotations

import html
import os
import re
from typing import Any

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# PyQt6-WebEngine is an optional extra (chat LaTeX rendering via MathJax). The
# chat panel degrades to rich-text (LaTeX shown as readable source) when it is
# not installed, so the import must not be a hard requirement.
try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_IMPORTED = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _WEBENGINE_IMPORTED = False

from ..llm.base import ChatMessage
from ..tools.base import ToolResult
from .dashboard import _open_external_url
from .tool_trace_panel import _format_tool_result, _to_json

_MATHJAX_SCRIPT_URL = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"


class ChatPanel(QWidget):
    """Conversation panel that emits user messages and renders final replies."""

    send_requested = pyqtSignal(str)
    stop_requested = pyqtSignal()
    new_chat_requested = pyqtSignal()
    history_requested = pyqtSignal()
    # Emits the selected chat-model key ("deepseek" / "kimi") when the user
    # picks a different brain from the header switcher.
    model_change_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ChatPanel")
        self.setMinimumWidth(520)
        self._streaming_bubble: MessageBodyWidget | None = None
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
        # Chat-model switcher (DeepSeek ⇄ Kimi K2.6). Hidden until MainWindow
        # populates it with ≥2 available brains via `set_models`. Uses
        # `activated` (user-only) so programmatic `set_active_model` never
        # echoes back as a change request.
        self._model_combo = QComboBox()
        self._model_combo.setObjectName("ModelSwitcher")
        self._model_combo.setToolTip("切换对话使用的模型（切换会开启新对话）")
        self._model_combo.hide()
        self._model_combo.activated.connect(self._emit_model_change)
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
        header_row.addWidget(self._model_combo)
        header_row.addWidget(self._thinking_toggle)
        header_row.addWidget(self._new_chat_button)
        header_row.addWidget(self._history_button)

        # Context-occupation gauge for the current conversation, under the
        # header it controls. A proactive read-out of how much of the model's
        # window is used, ahead of the agent's reactive over-length guard.
        self._context_meter = ContextMeter()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(header_row)
        layout.addWidget(self._context_meter)
        layout.addWidget(scroll, 1)
        layout.addLayout(input_row)

    def set_context_usage(
        self, used: int, window: int, *, estimated: bool = False
    ) -> None:
        """Update the context-occupation meter (driven by MainWindow)."""
        self._context_meter.set_usage(used, window, estimated=estimated)

    def set_models(
        self, models: list[tuple[str, str]], current_key: str | None
    ) -> None:
        """Populate the model switcher with `(key, label)` brains.

        Shown only when ≥2 brains are available (offline / single-key setups
        have nothing to switch between). The key rides as item data so
        `_emit_model_change` can report it.
        """
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for key, label in models:
            self._model_combo.addItem(label, key)
        self._model_combo.blockSignals(False)
        if current_key is not None:
            self.set_active_model(current_key)
        self._model_combo.setVisible(len(models) >= 2)

    def set_active_model(self, key: str) -> None:
        """Select `key` without emitting `model_change_requested`."""
        index = self._model_combo.findData(key)
        if index < 0:
            return
        self._model_combo.blockSignals(True)
        self._model_combo.setCurrentIndex(index)
        self._model_combo.blockSignals(False)

    def _emit_model_change(self, index: int) -> None:
        key = self._model_combo.itemData(index)
        if key:
            self.model_change_requested.emit(str(key))

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
            self._finalize_streaming_body(self._streaming_text)
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
        # Streaming stays in the lightweight QLabel (LaTeX shown as source); the
        # WebEngine math view is swapped in only at finalization.
        _set_message_body_text(self._streaming_bubble, self._streaming_text, "assistant")
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
        self._finalize_streaming_body(self._streaming_text or empty_fallback)
        self._streaming_bubble = None
        self._streaming_text = ""

    def _finalize_streaming_body(self, text: str) -> None:
        """Render the final text into the streaming bubble, swapping the QLabel
        for a MathMessageView when the finalized answer needs MathJax and the
        WebEngine extra is available. A no-op swap (WebEngine absent) leaves the
        QLabel in place, so the default path is unchanged."""
        body = self._streaming_bubble
        if body is None:
            return
        if isinstance(body, QLabel) and _should_use_math_view(text):
            new = MathMessageView()
            _replace_message_body(body, new)
            body = new
        _set_message_body_text(body, text, "assistant")

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

    def _add_message(self, author: str, text: str, role: str) -> MessageBodyWidget:
        bubble = QFrame()
        bubble.setObjectName("MessageBubble")
        bubble.setProperty("messageRole", role)
        bubble.setMaximumWidth(720 if role == "assistant" else 440)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        author_label = QLabel(author)
        author_label.setObjectName("MessageAuthor")

        # A finalized assistant message with LaTeX renders in a WebEngine+MathJax
        # view when the optional `math` extra is installed; otherwise (and for
        # user/system/streaming bubbles) this is a rich-text QLabel.
        body = _message_body_widget(role, text=text, finalized=True)
        _set_message_body_text(body, text, role)

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(10, 8, 10, 8)
        bubble_layout.setSpacing(4)
        bubble_layout.addWidget(author_label)
        bubble_layout.addWidget(body)

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
        return body

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


class ContextMeter(QWidget):
    """Slim gauge of how much of the model's context window is in use.

    A label ("上下文 12.3K / 1M · 1.2%") over a thin progress bar. With a 1M
    window most chats sit at a low single-digit percent — that is the intended
    message ("plenty of room"), so the absolute figure carries the meaning and
    the bar is deliberately linear (no rescaling to look fuller). The chunk
    colour escalates gold → red → bright-red as the window fills.
    """

    _WARN_PCT = 75.0
    _FULL_PCT = 90.0

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ContextMeter")
        self._label = QLabel("上下文 —")
        self._label.setObjectName("ContextMeterLabel")

        self._bar = QProgressBar()
        self._bar.setObjectName("ContextMeterBar")
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        # Permille range so a low-single-digit fill is still a visible sliver.
        self._bar.setRange(0, 1000)
        self._bar.setValue(0)
        self._set_level("ok")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 2)
        layout.setSpacing(3)
        layout.addWidget(self._label)
        layout.addWidget(self._bar)

    def set_usage(self, used: int, window: int, *, estimated: bool = False) -> None:
        used = max(0, int(used))
        window = max(0, int(window))
        if window <= 0:
            self._bar.setValue(0)
            self._label.setText("上下文 —")
            self._set_level("ok")
            return
        ratio = min(1.0, used / window)
        self._bar.setValue(round(ratio * 1000))
        pct = ratio * 100
        prefix = "约 " if estimated else ""
        self._label.setText(
            f"上下文 {prefix}{_fmt_tokens(used)} / {_fmt_tokens(window)} · {pct:.1f}%"
        )
        level = "ok" if pct < self._WARN_PCT else ("warn" if pct < self._FULL_PCT else "full")
        self._set_level(level)
        kind = "估算" if estimated else "实际"
        self._bar.setToolTip(
            f"对话已占用约 {used:,} / {window:,} tokens（{kind}），剩余 {window - used:,}"
        )

    def _set_level(self, level: str) -> None:
        if self._bar.property("level") == level:
            return
        self._bar.setProperty("level", level)
        self._bar.style().unpolish(self._bar)
        self._bar.style().polish(self._bar)


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


if _WEBENGINE_IMPORTED:

    class ExternalLinkPage(QWebEnginePage):
        """Intercept links from the embedded chat renderer and open them in Safari."""

        def acceptNavigationRequest(  # noqa: N802 - Qt callback.
            self,
            url: QUrl,
            nav_type: QWebEnginePage.NavigationType,
            is_main_frame: bool,
        ) -> bool:
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                _open_external_url(url.toString())
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    class MathMessageView(QWebEngineView):
        """Assistant-message renderer backed by WebEngine + MathJax."""

        _MIN_HEIGHT = 24
        _MAX_HEIGHT = 20_000

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("MessageText")
            self.setPage(ExternalLinkPage(self))
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setMinimumHeight(self._MIN_HEIGHT)
            self.setFixedHeight(self._MIN_HEIGHT)
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.settings().setAttribute(
                QWebEngineSettings.WebAttribute.ShowScrollBars,
                False,
            )
            self.loadFinished.connect(lambda _ok: self._schedule_height_syncs())
            self._plain_text = ""
            self._estimated_height = self._MIN_HEIGHT

        def setText(self, text: str) -> None:  # noqa: N802 - QLabel-compatible API.
            self._plain_text = text
            self._estimated_height = _estimate_message_html_height(text)
            self.setFixedHeight(self._estimated_height)
            self.updateGeometry()
            self.setHtml(_mathjax_document(text), QUrl("about:blank"))

        def text(self) -> str:
            return self._plain_text

        def _schedule_height_syncs(self) -> None:
            for delay in (0, 50, 150, 350, 800):
                QTimer.singleShot(delay, self._sync_height)

        def _sync_height(self) -> None:
            script = """
                (() => {
                    const height = () => {
                        const bodyTop = document.body.getBoundingClientRect().top;
                        const childBottom = Array.from(document.body.children).reduce(
                            (bottom, element) => Math.max(
                                bottom,
                                element.getBoundingClientRect().bottom - bodyTop
                            ),
                            0
                        );
                        return Math.ceil(Math.max(childBottom, 1));
                    };
                    const result = (ready) => ({height: height(), ready});
                    if (window.MathJax) {
                        const ready = MathJax.startup && MathJax.startup.promise
                            ? MathJax.startup.promise
                            : Promise.resolve();
                        return ready
                            .then(() => MathJax.typesetPromise ? MathJax.typesetPromise() : null)
                            .then(() => result(true))
                            .catch(() => result(false));
                    }
                    return result(true);
                })();
            """
            self.page().runJavaScript(script, self._apply_content_height)

        def _apply_content_height(self, value: object) -> None:
            try:
                if isinstance(value, dict):
                    height = int(float(value.get("height", self._MIN_HEIGHT)))
                    ready = bool(value.get("ready", False))
                else:
                    height = int(float(value))
                    ready = False
            except (TypeError, ValueError):
                height = self._MIN_HEIGHT
                ready = False
            next_height = max(self._MIN_HEIGHT, min(self._MAX_HEIGHT, height + 2))
            # Before MathJax/fonts settle, WebEngine can report a one-line height.
            # Keep the temporary estimate only until the browser reports a ready
            # layout; afterwards allow shrinking to remove extra whitespace.
            if not ready:
                next_height = max(next_height, self._estimated_height)
            if self.height() != next_height:
                self.setFixedHeight(next_height)
                self.updateGeometry()
                parent = self.parentWidget()
                if parent is not None:
                    parent.updateGeometry()
                    grandparent = parent.parentWidget()
                    if grandparent is not None:
                        grandparent.updateGeometry()

else:

    class MathMessageView:  # type: ignore[no-redef]
        """Importable placeholder when PyQt6-WebEngine (the math extra) is absent.

        Never instantiated: without the extra ``_webengine_enabled()`` is False,
        so ``_should_use_math_view()`` returns False and bubbles stay ``QLabel``.
        """

        _MIN_HEIGHT = 24
        _MAX_HEIGHT = 20_000

        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("PyQt6-WebEngine is required for MathMessageView")


MessageBodyWidget = QLabel | MathMessageView


def _message_body_widget(
    role: str,
    *,
    text: str = "",
    finalized: bool = True,
) -> MessageBodyWidget:
    if role == "assistant" and finalized and _should_use_math_view(text):
        return MathMessageView()
    label = QLabel()
    label.setObjectName("MessageText")
    label.setTextFormat(label.textFormat().RichText)
    label.setWordWrap(True)
    label.setOpenExternalLinks(False)
    label.linkActivated.connect(_open_external_url)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return label


def _estimate_message_html_height(body: str) -> int:
    """Conservative pre-layout height for MathJax messages.

    WebEngine's first scrollHeight can be too small while MathJax is still
    resolving fonts. This estimate keeps the Qt widget tall enough until the
    browser-side measurement catches up.
    """
    block_breaks = len(
        re.findall(r"</(?:div|li|tr|p|pre|h[1-6])>|<br\b", body, flags=re.IGNORECASE)
    )
    text = re.sub(r"<[^>]+>", "\n", body)
    text = html.unescape(text)
    text_lines = [line for line in text.splitlines() if line.strip()]
    visual_lines = max(1, len(text_lines), block_breaks)
    math_blocks = body.count("class='math-block'") + body.count('class="math-block"')
    table_rows = len(re.findall(r"<tr\b", body, flags=re.IGNORECASE))
    return min(
        MathMessageView._MAX_HEIGHT,
        max(
            MathMessageView._MIN_HEIGHT,
            4 + visual_lines * 16 + math_blocks * 14 + table_rows * 6,
        ),
    )


def _set_message_body_text(body: MessageBodyWidget, text: str, role: str) -> None:
    mathjax = isinstance(body, MathMessageView)
    body.setText(_message_html(text, role, mathjax=mathjax))


def _replace_message_body(old: MessageBodyWidget, new: MessageBodyWidget) -> None:
    parent = old.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is None:
        old.setParent(None)
        old.deleteLater()
        return
    index = layout.indexOf(old)
    if index < 0:
        old.setParent(None)
        old.deleteLater()
        return
    layout.removeWidget(old)
    old.setParent(None)
    old.deleteLater()
    layout.insertWidget(index, new)


def _should_use_math_view(text: str) -> bool:
    return _webengine_enabled() and _contains_latex(text)


def _contains_latex(text: str) -> bool:
    blocks = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.DOTALL)
    for block in blocks:
        if not block or block.startswith("`"):
            continue
        if re.search(r"\\\(.+?\\\)|\\\[.+?\\\]", block, flags=re.DOTALL):
            return True
        if re.search(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", block, flags=re.DOTALL):
            return True
        if re.search(r"(?<!\\)\$(?!\$).+?(?<!\\)\$", block, flags=re.DOTALL):
            return True
        if re.search(r"\\(frac|sum|int|sqrt|lim|begin|alpha|beta|gamma|theta|pi)\b", block):
            return True
    return False


def _webengine_enabled() -> bool:
    return (
        _WEBENGINE_IMPORTED
        and os.environ.get("PKU_CAPTAIN_DISABLE_WEBENGINE") != "1"
        and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
    )


def _mathjax_document(body: str) -> str:
    """Wrap rendered message HTML in a MathJax-enabled document."""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
        displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
        processEscapes: true
      }},
      chtml: {{
        scale: 1,
        matchFontHeight: false
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }}
    }};
  </script>
  <script async src="{_MATHJAX_SCRIPT_URL}"></script>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: auto;
      min-height: 0;
      background: transparent;
      color: #1f2328;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 13px;
      line-height: 1.35;
      overflow: visible;
    }}
    a {{
      color: #8c0000;
      text-decoration: underline;
    }}
    pre {{
      font-family: Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    code {{
      font-family: Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    table {{
      max-width: 100%;
    }}
    .math-inline {{
      color: #650000;
    }}
    .math-block {{
      color: #650000;
      overflow: visible;
      padding: 4px 0;
    }}
  </style>
</head>
<body>{body}</body>
</html>"""


def _message_html(text: str, role: str, *, mathjax: bool = True) -> str:
    body = _render_message_body(text, role, mathjax=mathjax)
    return body


def _render_message_body(text: str, role: str, *, mathjax: bool) -> str:
    if role != "assistant":
        return "<br>".join(_linkify_text(line) for line in text.splitlines())

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
            rendered.append(_render_markdownish_text(block, mathjax=mathjax))
    return "".join(rendered) or "（空回复）"


def _render_markdownish_text(text: str, *, mathjax: bool) -> str:
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
            out.append(_table_html(table_lines, mathjax=mathjax))
            continue
        block_formula = _collect_block_formula(lines, index)
        if block_formula is not None:
            if in_list:
                out.append("</ul>")
                in_list = False
            formula, next_index = block_formula
            out.append(_latex_block_html(formula, mathjax=mathjax))
            index = next_index
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
            out.append(f"<li>{_inline_markdown(stripped[2:], mathjax=mathjax)}</li>")
            index += 1
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            out.append(_heading_html(stripped[4:], weight=700, mathjax=mathjax))
        elif stripped.startswith("## "):
            out.append(_heading_html(stripped[3:], weight=800, mathjax=mathjax))
        elif stripped.startswith("# "):
            out.append(_heading_html(stripped[2:], weight=800, mathjax=mathjax))
        else:
            out.append(
                f"<div style='margin: 3px 0;'>{_inline_markdown(stripped, mathjax=mathjax)}</div>"
            )
        index += 1
    if in_list:
        out.append("</ul>")
    return "".join(out)


def _inline_markdown(text: str, *, mathjax: bool) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            rendered.append(
                "<code style='background: #fffaf7; padding: 1px 4px; border-radius: 4px;'>"
                f"{html.escape(part[1:-1])}</code>"
            )
            continue
        rendered.append(_inline_markdown_no_code(part, mathjax=mathjax))
    return "".join(rendered)


def _inline_markdown_no_code(text: str, *, mathjax: bool) -> str:
    pattern = re.compile(r"\\\((.+?)\\\)|(?<!\\)\$(?!\$)(.+?)(?<!\\)\$")
    rendered: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        rendered.append(_inline_text_without_latex(text[cursor : match.start()]))
        rendered.append(
            _latex_inline_html(match.group(1) or match.group(2) or "", mathjax=mathjax)
        )
        cursor = match.end()
    rendered.append(_inline_text_without_latex(text[cursor:]))
    return "".join(rendered)


def _inline_text_without_latex(text: str) -> str:
    linked = _linkify_text(text)
    linked = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", linked)
    return linked


def _linkify_text(text: str) -> str:
    """Render Markdown links and bare URLs as safe HTML anchors."""
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|(https?://[^\s<>()]+)")
    rendered: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        rendered.append(html.escape(text[cursor : match.start()]))
        label = match.group(1)
        markdown_url = match.group(2)
        bare_url = match.group(3)
        url = markdown_url or bare_url or ""
        if bare_url:
            url, trailing = _split_url_trailing_punctuation(url)
            rendered.append(_anchor_html(url, url))
            rendered.append(html.escape(trailing))
        else:
            rendered.append(_anchor_html(url, label or url))
        cursor = match.end()
    rendered.append(html.escape(text[cursor:]))
    return "".join(rendered)


def _split_url_trailing_punctuation(url: str) -> tuple[str, str]:
    trailing = ""
    while url and url[-1] in ".,;:!?，。；：！？":
        trailing = url[-1] + trailing
        url = url[:-1]
    return url, trailing


def _anchor_html(url: str, label: str) -> str:
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label)
    return f"<a href='{safe_url}'>{safe_label}</a>"


def _heading_html(text: str, *, weight: int, mathjax: bool) -> str:
    return (
        f"<div style='font-weight: {weight}; margin-top: 8px;'>"
        f"{_inline_markdown(text, mathjax=mathjax)}</div>"
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


def _table_html(lines: list[str], *, mathjax: bool) -> str:
    headers = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    column_count = max([len(headers), *(len(row) for row in rows)] or [0])
    if column_count == 0:
        return ""

    header_cells = "".join(
        "<th style='background: #fff6ed; color: #650000; "
        "font-weight: 700; padding: 5px 7px; border: 1px solid #eadbd5;'>"
        f"{_inline_markdown(_cell_at(headers, column), mathjax=mathjax)}</th>"
        for column in range(column_count)
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            "<td style='padding: 5px 7px; border: 1px solid #eadbd5;'>"
            f"{_inline_markdown(_cell_at(row, column), mathjax=mathjax)}</td>"
            for column in range(column_count)
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        "<table cellspacing='0' cellpadding='0' "
        "style='border-collapse: collapse; margin: 8px 0;'>"
        f"<tr>{header_cells}</tr>{''.join(body_rows)}</table>"
    )


def _collect_block_formula(lines: list[str], index: int) -> tuple[str, int] | None:
    stripped = lines[index].strip()
    if stripped.startswith("$$"):
        return _collect_delimited_formula(lines, index, "$$", "$$")
    if stripped.startswith("\\["):
        return _collect_delimited_formula(lines, index, "\\[", "\\]")
    return None


def _collect_delimited_formula(
    lines: list[str],
    index: int,
    opener: str,
    closer: str,
) -> tuple[str, int]:
    first = lines[index].strip()
    remainder = first[len(opener) :]
    if remainder.endswith(closer) and len(remainder) > len(closer):
        return remainder[: -len(closer)].strip(), index + 1

    formula_lines = [remainder] if remainder else []
    index += 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.endswith(closer):
            formula_lines.append(stripped[: -len(closer)])
            return "\n".join(formula_lines).strip(), index + 1
        formula_lines.append(line)
        index += 1
    return "\n".join(formula_lines).strip(), index


def _latex_inline_html(formula: str, *, mathjax: bool) -> str:
    if mathjax:
        return f"<span class='math-inline'>\\({_latex_source_text(formula)}\\)</span>"
    return (
        "<span style='font-family: Menlo, Consolas, monospace; "
        "background: #fffaf7; border: 1px solid #eadbd5; border-radius: 4px; "
        "padding: 0 4px; color: #650000;'>"
        f"{_latex_display_text(formula)}</span>"
    )


def _latex_block_html(formula: str, *, mathjax: bool) -> str:
    if mathjax:
        return f"<div class='math-block'>\\[{_latex_source_text(formula)}\\]</div>"
    return (
        "<div style='font-family: Menlo, Consolas, monospace; "
        "background: #fffaf7; border: 1px solid #eadbd5; border-radius: 6px; "
        "padding: 8px; margin: 8px 0; color: #650000; text-align: center; "
        "white-space: pre-wrap;'>"
        f"{_latex_display_text(formula)}</div>"
    )


def _latex_source_text(formula: str) -> str:
    return html.escape(formula.strip())


def _latex_display_text(formula: str) -> str:
    text = html.escape(formula.strip())
    replacements = {
        r"\times": "×",
        r"\cdot": "·",
        r"\leq": "≤",
        r"\geq": "≥",
        r"\neq": "≠",
        r"\approx": "≈",
        r"\infty": "∞",
        r"\sum": "∑",
        r"\int": "∫",
        r"\alpha": "α",
        r"\beta": "β",
        r"\gamma": "γ",
        r"\delta": "δ",
        r"\lambda": "λ",
        r"\mu": "μ",
        r"\pi": "π",
        r"\theta": "θ",
    }
    for raw, rendered in replacements.items():
        text = text.replace(html.escape(raw), rendered)
    return text


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
