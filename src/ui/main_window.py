"""PyQt6 main window shell.

Three panel slots — dashboard, chat sidebar, tool-call panel — laid out
side by side so the UI lane owner can populate each independently.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    """Top-level window. Layout: dashboard | chat sidebar | tool-call panel."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PKU Captain")
        self.resize(1280, 800)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_dashboard())
        splitter.addWidget(self._build_chat_sidebar())
        splitter.addWidget(self._build_tool_call_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        self.setCentralWidget(splitter)

    def _build_dashboard(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Dashboard"))
        layout.addStretch()
        return widget

    def _build_chat_sidebar(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Chat"))
        layout.addStretch()
        return widget

    def _build_tool_call_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Tool Calls"))
        layout.addStretch()
        return widget
