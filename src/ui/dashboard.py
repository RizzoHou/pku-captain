"""Dashboard entry surface for PKU Captain."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .formatters import parse_datetime, upcoming_assignments


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
        self._weather_label = QLabel("天气加载中...")
        self._weather_label.setObjectName("HeaderWeather")
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
        header.addWidget(self._weather_label, 2, 0)
        header.addWidget(self._updated_label, 3, 0)
        header.addWidget(self._otp_input, 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._refresh_button, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._briefing_button, 0, 3, 2, 1, Qt.AlignmentFlag.AlignRight)

        self._cards = {
            "schedule": ScheduleCard(),
            "pku3b_assignments": AssignmentTodoCard(),
            "pku3b_announcements": DashboardCard("课程通知", "等待接入 pku3b_announcements"),
            "lecture": DashboardCard("讲座推荐", "等待接入 lecture 工具"),
        }

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(12)
        grid.addWidget(self._cards["schedule"], 0, 0, 1, 2)
        grid.addWidget(self._cards["pku3b_assignments"], 1, 0)
        grid.addWidget(self._cards["pku3b_announcements"], 1, 1)
        grid.addWidget(self._cards["lecture"], 2, 0, 1, 2)

        scroll = QScrollArea()
        scroll.setObjectName("DashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(grid_host)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)

    def set_loading(self, key: str) -> None:
        if key == "weather":
            self._weather_label.setText("天气加载中...")
            return
        if key in self._cards:
            self._cards[key].set_body("加载中...", "loading")

    def set_data(self, key: str, body: str) -> None:
        if key in self._cards:
            self._cards[key].set_body(body, "data")

    def set_schedule(self, data: dict[str, object]) -> None:
        card = self._cards.get("schedule")
        if isinstance(card, ScheduleCard):
            card.set_schedule(data)

    def set_assignments(self, data: dict[str, object]) -> None:
        card = self._cards.get("pku3b_assignments")
        if isinstance(card, AssignmentTodoCard):
            card.set_assignments(data)

    def set_weather(self, data: dict[str, object]) -> None:
        self._weather_label.setText(_weather_text(data))

    def set_error(self, key: str, message: str) -> None:
        if key == "weather":
            self._weather_label.setText(f"天气不可用：{message}")
            return
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


class AssignmentTodoCard(QFrame):
    """Dashboard card that renders upcoming assignments as a todo list."""

    _COLLAPSED_LIMIT = 3

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(196)
        self._assignments: list[dict[str, object]] = []
        self._expanded = False

        title_label = QLabel("近期 DDL")
        title_label.setObjectName("CardTitle")
        hint_label = QLabel("待办事项 · 按截止时间排序")
        hint_label.setObjectName("CardBody")

        self._list_host = QWidget()
        self._list_host.setObjectName("TodoList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(7)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        layout.addWidget(self._list_host)
        layout.addStretch()

        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        self._assignments = []
        self._expanded = False
        self._clear_items()
        label = QLabel(text)
        label.setObjectName("CardBody")
        label.setWordWrap(True)
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._list_layout.addWidget(label)

    def set_assignments(self, data: dict[str, object]) -> None:
        self._assignments = upcoming_assignments(data.get("assignments"))
        self._expanded = False
        self._render_assignments()

    def _render_assignments(self) -> None:
        self._clear_items()
        if not self._assignments:
            self.set_body("暂无未完成作业", "data")
            return

        visible = (
            self._assignments
            if self._expanded
            else self._assignments[: self._COLLAPSED_LIMIT]
        )
        for item in visible:
            self._list_layout.addWidget(_todo_row(item))
        hidden_count = len(self._assignments) - len(visible)
        if len(self._assignments) > self._COLLAPSED_LIMIT:
            toggle = QPushButton(
                "收起" if self._expanded else f"展开全部（还有 {hidden_count} 项）"
            )
            toggle.setObjectName("InlineToggleButton")
            toggle.clicked.connect(self._toggle_expanded)
            self._list_layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._list_layout.addStretch()

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._render_assignments()

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class ScheduleCard(QFrame):
    """Seven-day calendar-style course table card."""

    _DAYS = [
        ("mon", "周一"),
        ("tue", "周二"),
        ("wed", "周三"),
        ("thu", "周四"),
        ("fri", "周五"),
        ("sat", "周六"),
        ("sun", "周日"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        title_label = QLabel("完整课表")
        title_label.setObjectName("CardTitle")
        hint_label = QLabel("点击课程块查看上课信息")
        hint_label.setObjectName("CardBody")

        self._calendar_host = QWidget()
        self._calendar_host.setObjectName("ScheduleGrid")
        self._calendar_layout = QGridLayout(self._calendar_host)
        self._calendar_layout.setContentsMargins(0, 0, 0, 0)
        self._calendar_layout.setHorizontalSpacing(7)
        self._calendar_layout.setVerticalSpacing(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        layout.addWidget(self._calendar_host, 1)

        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        self._clear_calendar()
        label = QLabel(text)
        label.setObjectName("CardBody")
        label.setWordWrap(True)
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._calendar_layout.addWidget(label, 0, 0)

    def set_schedule(self, data: dict[str, object]) -> None:
        blocks = data.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            self.set_body("暂无课表数据", "data")
            return

        self._clear_calendar()
        normalized_blocks: list[dict[str, object]] = []
        max_slot = max(
            12,
            max(
                (
                    int(item.get("end_slot", 0))
                    for item in blocks
                    if isinstance(item, dict) and isinstance(item.get("end_slot"), int)
                ),
                default=0,
            ),
        )
        day_columns = {key: index for index, (key, _) in enumerate(self._DAYS, start=1)}
        occupied_cells: set[tuple[str, int]] = set()
        for item in blocks:
            if not isinstance(item, dict):
                continue
            day_key = str(item.get("day_key", ""))
            if day_key not in day_columns:
                continue
            start = max(1, int(item.get("start_slot", 1)))
            end = max(start, int(item.get("end_slot", start)))
            normalized = dict(item)
            normalized["start_slot"] = start
            normalized["end_slot"] = end
            normalized_blocks.append(normalized)
            for slot in range(start, end + 1):
                occupied_cells.add((day_key, slot))

        self._calendar_layout.addWidget(_header_label("节"), 0, 0)
        for column, (_, day_name) in enumerate(self._DAYS, start=1):
            self._calendar_layout.addWidget(_header_label(day_name), 0, column)

        for slot in range(1, max_slot + 1):
            self._calendar_layout.setRowMinimumHeight(slot, 28)
            self._calendar_layout.setRowStretch(slot, 1)
            self._calendar_layout.addWidget(_slot_label(str(slot)), slot, 0)
            for column, (day_key, _) in enumerate(self._DAYS, start=1):
                if (day_key, slot) in occupied_cells:
                    continue
                empty = QLabel("")
                empty.setObjectName("ScheduleEmpty")
                self._calendar_layout.addWidget(empty, slot, column)

        for item in normalized_blocks:
            day_key = str(item.get("day_key", ""))
            column = day_columns.get(day_key)
            if column is None:
                continue
            start = int(item["start_slot"])
            end = int(item["end_slot"])
            title = str(item.get("title", "未命名课程"))
            detail = str(item.get("detail", ""))
            button = QPushButton(title)
            button.setObjectName("CourseBlock")
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            button.setToolTip(detail or title)
            button.clicked.connect(
                lambda _checked=False, course=dict(item): self._show_course_detail(course)
            )
            self._calendar_layout.addWidget(button, start, column, end - start + 1, 1)

        self._calendar_layout.setColumnMinimumWidth(0, 24)
        for column in range(1, 8):
            self._calendar_layout.setColumnMinimumWidth(column, 78)
            self._calendar_layout.setColumnStretch(column, 1)

    def _show_course_detail(self, course: dict[str, object]) -> None:
        start = course.get("start_slot", "?")
        end = course.get("end_slot", start)
        slot = f"第{start}节" if start == end else f"第{start}-{end}节"
        message = "\n".join(
            [
                f"课程：{course.get('title', '未命名课程')}",
                f"时间：{course.get('day_name', '')} {slot}",
                f"详情：{course.get('detail') or '暂无详细信息'}",
            ]
        )
        QMessageBox.information(self, "课程详情", message)

    def _clear_calendar(self) -> None:
        while self._calendar_layout.count():
            item = self._calendar_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


def _header_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("ScheduleHeader")
    return label


def _slot_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("ScheduleSlot")
    return label


def _todo_row(item: dict[str, object]) -> QFrame:
    row = QFrame()
    row.setObjectName("TodoRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    marker = QLabel("")
    marker.setObjectName("TodoMarker")
    marker.setFixedSize(12, 12)

    title = QLabel(str(item.get("title") or "未命名作业"))
    title.setObjectName("TodoTitle")
    title.setWordWrap(True)

    course = QLabel(str(item.get("course_name") or item.get("course_title") or "未知课程"))
    course.setObjectName("TodoCourse")
    course.setWordWrap(True)

    deadline = QLabel(_deadline_text(item))
    deadline.setObjectName("TodoDeadline")
    deadline.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    deadline.setMinimumWidth(112)

    text_layout = QVBoxLayout()
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)
    text_layout.addWidget(title)
    text_layout.addWidget(course)

    layout = QHBoxLayout(row)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(9)
    layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
    layout.addLayout(text_layout, 1)
    layout.addWidget(deadline, 0)
    return row


def _deadline_text(item: dict[str, object]) -> str:
    raw = item.get("deadline_raw") or item.get("deadline_iso")
    deadline = parse_datetime(item.get("deadline_iso"))
    if deadline is None:
        return str(raw or "期限未知")

    now = datetime.now().astimezone()
    date_text = deadline.strftime("%m-%d %H:%M")
    days = (deadline.date() - now.date()).days
    if days < 0:
        return f"已过期 · {date_text}"
    if days == 0:
        return f"今天 · {date_text}"
    if days == 1:
        return f"明天 · {date_text}"
    if days <= 7:
        return f"{days} 天后 · {date_text}"
    return date_text


def _weather_text(data: dict[str, object]) -> str:
    desc = str(data.get("weather_description") or "未知")
    return "{icon} {location}：{desc}，{temp}°C，体感 {feels}°C".format(
        icon=_weather_icon(desc),
        location=data.get("location", "未知地点"),
        desc=desc,
        temp=data.get("temperature_c", "?"),
        feels=data.get("apparent_temperature_c", "?"),
    )


def _weather_icon(desc: str) -> str:
    lowered = desc.lower()
    if "雷" in desc or "thunder" in lowered:
        return "⛈️"
    if "雪" in desc or "snow" in lowered:
        return "❄️"
    if "雨" in desc or "rain" in lowered or "shower" in lowered:
        return "🌧️"
    if "阴" in desc or "cloud" in lowered or "overcast" in lowered:
        return "☁️"
    if "雾" in desc or "霾" in desc or "fog" in lowered or "haze" in lowered:
        return "🌫️"
    if "晴" in desc or "clear" in lowered or "sun" in lowered:
        return "☀️"
    return "🌤️"
