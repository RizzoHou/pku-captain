"""Chat sidebar widgets for user input and assistant replies."""

from __future__ import annotations

import html

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


class ChatPanel(QWidget):
    """Conversation panel that emits user messages and renders final replies."""

    send_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ChatPanel")

        self._message_layout = QVBoxLayout()
        self._message_layout.setSpacing(10)
        self._message_layout.addStretch()

        message_host = QWidget()
        message_host.setObjectName("MessageHost")
        message_host.setLayout(self._message_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
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
        self._add_message("PKU Captain", text or "（空回复）", "assistant")

    def add_system_message(self, text: str) -> None:
        self._add_message("系统", text, "system")

    def _emit_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.send_requested.emit(text)

    def _add_message(self, author: str, text: str, role: str) -> None:
        bubble = QLabel()
        bubble.setTextFormat(bubble.textFormat().RichText)
        bubble.setWordWrap(True)
        bubble.setOpenExternalLinks(True)
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        bubble.setText(_message_html(author, text, role))

        row = QHBoxLayout()
        if role == "user":
            row.addStretch()
            row.addWidget(bubble, 0)
        else:
            row.addWidget(bubble, 0)
            row.addStretch()

        row_host = QWidget()
        row_host.setLayout(row)
        self._message_layout.insertWidget(self._message_layout.count() - 1, row_host)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())


def _message_html(author: str, text: str, role: str) -> str:
    body = html.escape(text).replace("\n", "<br>")
    author_html = html.escape(author)
    colors = {
        "user": ("#8c0000", "#ffffff"),
        "assistant": ("#ffffff", "#1f2937"),
        "system": ("#fff6ed", "#8c0000"),
    }
    background, foreground = colors.get(role, colors["assistant"])
    return (
        f"<div style='max-width: 420px; padding: 10px 12px; "
        f"border-radius: 8px; background: {background}; color: {foreground};'>"
        f"<div style='font-weight: 600; margin-bottom: 4px;'>{author_html}</div>"
        f"<div>{body}</div>"
        "</div>"
    )


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
