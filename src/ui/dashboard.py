"""Dashboard entry surface for PKU Captain."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class DashboardPanel(QWidget):
    """Dashboard shell with the Week-2 core information widgets."""

    morning_briefing_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, *, mode_label: str) -> None:
        super().__init__()
        self.setObjectName("DashboardPanel")

        title = QLabel("PKU Captain 北大信息助手")
        title.setObjectName("DashboardTitle")
        subtitle = QLabel(f"今日信息总览 · {mode_label}")
        subtitle.setObjectName("DashboardSubtitle")
        self._updated_label = QLabel("尚未刷新")
        self._updated_label.setObjectName("DashboardSubtitle")
        self._otp_input = QLineEdit()
        self._otp_input.setPlaceholderText("课表 OTP")
        self._otp_input.setFixedWidth(96)
        self._otp_input.setEchoMode(QLineEdit.EchoMode.Password)

        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setObjectName("SecondaryButton")
        self._refresh_button.clicked.connect(self.refresh_requested)
        self._briefing_button = QPushButton("今日简报")
        self._briefing_button.setObjectName("PrimaryButton")
        self._briefing_button.clicked.connect(self.morning_briefing_requested)

        header = QGridLayout()
        header.addWidget(title, 0, 0)
        header.addWidget(subtitle, 1, 0)
        header.addWidget(self._updated_label, 2, 0)
        header.addWidget(self._otp_input, 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._refresh_button, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._briefing_button, 0, 3, 2, 1, Qt.AlignmentFlag.AlignRight)

        self._cards = {
            "schedule": DashboardCard("今日课表", "等待接入 pku3b 课表数据"),
            "pku3b_assignments": DashboardCard("近期 DDL", "等待接入 pku3b_assignments"),
            "pku3b_announcements": DashboardCard("课程通知", "等待接入 pku3b_announcements"),
            "weather": DashboardCard("天气", "等待接入 weather 工具"),
            "lecture": DashboardCard("讲座推荐", "等待接入 lecture 工具"),
        }

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self._cards["schedule"], 0, 0)
        grid.addWidget(self._cards["pku3b_assignments"], 0, 1)
        grid.addWidget(self._cards["pku3b_announcements"], 1, 0)
        grid.addWidget(self._cards["weather"], 1, 1)
        grid.addWidget(self._cards["lecture"], 2, 0, 1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addLayout(grid)
        layout.addStretch()

    def set_loading(self, key: str) -> None:
        if key in self._cards:
            self._cards[key].set_body("加载中...", "loading")

    def set_data(self, key: str, body: str) -> None:
        if key in self._cards:
            self._cards[key].set_body(body, "data")

    def set_error(self, key: str, message: str) -> None:
        if key in self._cards:
            self._cards[key].set_body(f"不可用：{message}", "error")

    def set_refresh_busy(self, busy: bool) -> None:
        self._refresh_button.setEnabled(not busy)
        self._refresh_button.setText("刷新中" if busy else "刷新")

    def set_updated_text(self, text: str) -> None:
        self._updated_label.setText(text)

    def set_briefing_busy(self, busy: bool) -> None:
        self._briefing_button.setEnabled(not busy)
        self._briefing_button.setText("生成中" if busy else "今日简报")

    def otp_code(self) -> str:
        return self._otp_input.text().strip()


class DashboardCard(QFrame):
    """Small fixed-purpose dashboard card."""

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(142)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        self._body_label = QLabel(body)
        self._body_label.setWordWrap(True)
        self._body_label.setObjectName("CardBody")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._body_label)
        layout.addStretch()

    def set_body(self, text: str, state: str = "data") -> None:
        self._body_label.setText(text)
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._body_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
