"""Chat sidebar widgets for user input and assistant replies."""

from __future__ import annotations

import html
import re
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
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

from .tool_trace_panel import _format_tool_result, _to_json


class ChatPanel(QWidget):
    """Conversation panel that emits user messages and renders final replies."""

    send_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ChatPanel")
        self.setMinimumWidth(520)
        self._streaming_bubble: QLabel | None = None
        self._streaming_text = ""
        self._tool_rows: dict[str, InlineToolCall] = {}

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

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        title = QLabel("对话")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        layout.addLayout(input_row)

    def set_busy(self, busy: bool) -> None:
        """Disable input while a turn is running."""
        self._input.setEnabled(not busy)
        self._send_button.setEnabled(not busy)
        self._send_button.setText("处理中" if busy else "发送")

    def add_user_message(self, text: str) -> None:
        self._add_message("你", text, "user")

    def add_assistant_message(self, text: str) -> None:
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

    def _emit_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.send_requested.emit(text)

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
