"""Dashboard entry surface for PKU Captain."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..tools.base import Tool, ToolRegistry
from ..tools.treehole_updates import (
    DEFAULT_NOTIFY_INTERVAL,
    TreeholeAuthService,
    TreeholeInboxStore,
    TreeholeNotificationService,
)
from .formatters import parse_datetime, upcoming_assignments
from .tool_call_worker import run_async

if TYPE_CHECKING:
    from ..core import MemoryLearnService


TREEHOLE_WEB_URL = "https://treehole.pku.edu.cn/ch/web/"


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt callback.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _open_external_url(url: str) -> bool:
    target = url.strip()
    if not target:
        return False
    if sys.platform == "darwin":
        result = subprocess.run(
            ["open", "-a", "Safari", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return True
    return QDesktopServices.openUrl(QUrl(target))


class DashboardPanel(QWidget):
    """Dashboard shell with the Week-2 core information widgets."""

    morning_briefing_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    partial_refresh_requested = pyqtSignal(list)
    # Emitted after the treehole dialog closes so the window can reconfigure the
    # auto-sync timer (notification enable/disable/interval may have changed).
    treehole_settings_changed = pyqtSignal()

    def __init__(
        self,
        *,
        mode_label: str,
        tools: ToolRegistry | None = None,
        memory_learner: MemoryLearnService | None = None,
        treehole_inbox: TreeholeInboxStore | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("DashboardPanel")
        self._tools = tools
        self._memory_learner = memory_learner
        # Accumulates unread treehole updates so a poll's result sticks on the
        # card instead of vanishing on the next empty poll. In-memory by default
        # (tests / no-disk); MainWindow injects a persisted store.
        self._treehole_inbox = treehole_inbox or TreeholeInboxStore()

        title = QLabel("PKU Captain")
        title.setObjectName("DashboardTitle")
        subtitle = QLabel(f"今日信息总览 · {mode_label}")
        subtitle.setObjectName("DashboardSubtitle")
        self._updated_label = QLabel("尚未刷新")
        self._updated_label.setObjectName("DashboardSubtitle")
        self._treehole_data: dict[str, object] = {
            "status": "loading",
            "message": "树洞消息加载中...",
            "unread_count": 0,
            "updates": [],
        }
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
        self._treehole_button = QPushButton("◉ 树洞")
        self._treehole_button.setObjectName("HeaderTreeholeButton")
        self._treehole_button.setToolTip("查看树洞新消息")
        self._treehole_button.clicked.connect(self._show_treehole_dialog)
        self._reminders_button = QPushButton("提醒")
        self._reminders_button.setObjectName("SecondaryButton")
        self._reminders_button.clicked.connect(self._show_reminders_dialog)
        self._memory_button = QPushButton("记忆")
        self._memory_button.setObjectName("SecondaryButton")
        self._memory_button.clicked.connect(self._show_memory_dialog)
        self._knowledge_button = QPushButton("知识库")
        self._knowledge_button.setObjectName("SecondaryButton")
        self._knowledge_button.clicked.connect(self._show_knowledge_dialog)

        header = QGridLayout()
        header.addWidget(title, 0, 0)
        header.addWidget(subtitle, 1, 0)
        header.addWidget(self._updated_label, 2, 0)
        header.addWidget(self._otp_input, 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._refresh_button, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._briefing_button, 0, 3, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._treehole_button, 0, 4, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._reminders_button, 0, 5, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._memory_button, 0, 6, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._knowledge_button, 0, 7, 2, 1, Qt.AlignmentFlag.AlignRight)

        self._cards = {
            "schedule": ScheduleCard(),
            "pku3b_assignments": AssignmentTodoCard(),
            "treehole_updates": TreeholeMessagesCard(),
            "dean_updates": DeanUpdatesCard(),
            "plib_materials": PLibMaterialsCard(),
            "pku3b_announcements": AnnouncementsCard(),
            "lecture": LecturesCard(),
        }
        treehole_card = self._cards["treehole_updates"]
        if isinstance(treehole_card, TreeholeMessagesCard):
            treehole_card.view_requested.connect(self._show_treehole_dialog)
            treehole_card.refresh_requested.connect(
                self._partial_refresh_emitter("treehole_updates")
            )
        dean_card = self._cards["dean_updates"]
        if isinstance(dean_card, DeanUpdatesCard):
            dean_card.refresh_requested.connect(self._partial_refresh_emitter("dean_updates"))
        plib_card = self._cards["plib_materials"]
        if isinstance(plib_card, PLibMaterialsCard):
            plib_card.login_requested.connect(self._show_plib_login_dialog)
            plib_card.search_requested.connect(self._show_plib_dialog)
            plib_card.refresh_requested.connect(
                self._partial_refresh_emitter("plib_materials")
            )
        announcements_card = self._cards["pku3b_announcements"]
        if isinstance(announcements_card, AnnouncementsCard):
            announcements_card.detail_requested.connect(self._show_announcement_detail)
            announcements_card.refresh_requested.connect(
                self._partial_refresh_emitter("pku3b_announcements")
            )
        lecture_card = self._cards["lecture"]
        if isinstance(lecture_card, LecturesCard):
            lecture_card.detail_requested.connect(self._show_lecture_detail)
            lecture_card.search_requested.connect(self._show_lecture_search_dialog)
            lecture_card.refresh_requested.connect(
                self._partial_refresh_emitter("lecture")
            )
        assignment_card = self._cards["pku3b_assignments"]
        if isinstance(assignment_card, AssignmentTodoCard):
            assignment_card.add_to_calendar_requested.connect(self._show_calendar_dialog)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(12)
        grid.addWidget(self._cards["schedule"], 0, 0, 1, 2)
        grid.addWidget(self._cards["pku3b_assignments"], 1, 0)
        grid.addWidget(self._cards["treehole_updates"], 1, 1)
        grid.addWidget(self._cards["dean_updates"], 2, 0)
        grid.addWidget(self._cards["pku3b_announcements"], 2, 1)
        grid.addWidget(self._cards["plib_materials"], 3, 0)
        grid.addWidget(self._cards["lecture"], 3, 1)

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

        # Online-only entry points are disabled when their tool is not
        # registered (offline mode), so the GUI never reaches a network /
        # subprocess tool that the agent factory deliberately left out.
        self._treehole_button.setEnabled("treehole_updates" in (self._tools or ()))
        self._knowledge_button.setEnabled("knowledge_search" in (self._tools or ()))
        if isinstance(assignment_card, AssignmentTodoCard):
            assignment_card.set_calendar_enabled("calendar_reminder" in (self._tools or ()))

        # Reflect unread carried over from a previous session before the first poll.
        if self._treehole_inbox.unread_count():
            self._render_treehole()

    def _partial_refresh_emitter(self, *keys: str) -> Callable[[], None]:
        """Build a slot that requests a refresh scoped to the given tool keys,
        so a single card's refresh button reloads only its own data instead of
        triggering a full-dashboard refresh."""
        scoped = list(keys)
        return lambda: self.partial_refresh_requested.emit(scoped)

    def _online_tool(self, name: str) -> Tool | None:
        """Look up a registered tool by name; None if offline / not registered."""
        return self._tools.find(name) if self._tools is not None else None

    def _require_tool(self, name: str, title: str) -> Tool | None:
        tool = self._online_tool(name)
        if tool is None:
            QMessageBox.information(
                self, title, "该功能需要在线模式，当前未启用对应工具。"
            )
        return tool

    def set_loading(self, key: str) -> None:
        if key in self._cards:
            self._cards[key].set_body("加载中...", "loading")
        if key == "treehole_updates":
            self._set_treehole_button(0, "树洞消息加载中...")

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

    def set_announcements(self, data: dict[str, object]) -> None:
        card = self._cards.get("pku3b_announcements")
        if isinstance(card, AnnouncementsCard):
            card.set_announcements(data)

    def set_lectures(self, data: list[object]) -> None:
        card = self._cards.get("lecture")
        if isinstance(card, LecturesCard):
            card.set_lectures(data)

    def set_treehole_updates(self, data: dict[str, object]) -> None:
        """Merge a poll's updates into the unread inbox and re-render the card.

        Accumulates rather than replaces, so a reply surfaced by one poll stays
        visible until the user opens the dialog (mark-as-read) — the next empty
        poll no longer blanks it. The poll's own ``message`` is only used when
        the inbox is empty; otherwise the count drives the summary.
        """
        updates = data.get("updates")
        if isinstance(updates, list):
            self._treehole_inbox.merge([u for u in updates if isinstance(u, dict)])
        self._render_treehole(
            fallback_message=str(data.get("message") or ""),
            status=str(data.get("status") or "ok"),
        )

    def _render_treehole(self, *, fallback_message: str = "", status: str = "ok") -> None:
        entries = self._treehole_inbox.entries()
        count = self._treehole_inbox.unread_count()
        if status in {"error", "auth_required", "needs_sms"}:
            message = fallback_message or "树洞不可用"
        elif count:
            message = f"有 {count} 条树洞新回复"
        else:
            message = fallback_message or "暂无树洞新回复"
        display: dict[str, object] = {
            "status": status,
            "message": message,
            "unread_count": count,
            "updates": entries,
        }
        self._treehole_data = display
        self._set_treehole_button(count, message)
        card = self._cards.get("treehole_updates")
        if isinstance(card, TreeholeMessagesCard):
            card.set_updates(display)

    def set_dean_updates(self, data: dict[str, object]) -> None:
        card = self._cards.get("dean_updates")
        if isinstance(card, DeanUpdatesCard):
            card.set_updates(data)

    def set_plib_materials(self, data: dict[str, object]) -> None:
        card = self._cards.get("plib_materials")
        if isinstance(card, PLibMaterialsCard):
            card.set_quota(data)

    def set_error(self, key: str, message: str) -> None:
        if key == "treehole_updates":
            # Keep accumulated unread entries visible; only the summary shows the
            # error, so a transient poll failure does not wipe the inbox.
            self._render_treehole(
                fallback_message=f"树洞不可用：{message}", status="error"
            )
            return
        if key == "plib_materials":
            card = self._cards.get("plib_materials")
            if isinstance(card, PLibMaterialsCard):
                card.set_body(f"P-Lib 不可用：{message}", "error")
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

    def _set_treehole_button(self, count: int, tooltip: str) -> None:
        self._treehole_button.setText(f"◉ 树洞 {count}" if count else "◉ 树洞")
        self._treehole_button.setToolTip(tooltip or "查看树洞新消息")
        self._treehole_button.setProperty("hasUnread", bool(count))
        self._treehole_button.style().unpolish(self._treehole_button)
        self._treehole_button.style().polish(self._treehole_button)

    def _show_treehole_dialog(self) -> None:
        if self._require_tool("treehole_updates", "树洞新消息") is None:
            return
        dialog = TreeholeMessagesDialog(self._treehole_data, self)
        dialog.auth_changed.connect(self._partial_refresh_emitter("treehole_updates"))
        # Opening the list marks the accumulated unread as read: empty the inbox
        # (the dialog already captured a snapshot) so the card/badge reset.
        self._treehole_inbox.clear()
        self._render_treehole()
        dialog.exec()
        # The dialog nests the notification settings dialog; once it closes any
        # enable/disable/interval change is persisted, so reconfigure the timer.
        self.treehole_settings_changed.emit()

    def _show_plib_dialog(self) -> None:
        tool = self._require_tool("plib_materials", "P-Lib 资料搜索")
        if tool is None:
            return
        PLibSearchDialog(tool, self).exec()

    def _show_plib_login_dialog(self) -> None:
        tool = self._require_tool("plib_materials", "P-Lib 登录")
        if tool is None:
            return
        dialog = PLibLoginDialog(tool, self)
        dialog.auth_changed.connect(self._partial_refresh_emitter("plib_materials"))
        dialog.exec()

    def _show_announcement_detail(self, announcement_id: str) -> None:
        tool = self._require_tool("pku3b_announcements", "课程通知详情")
        if tool is None:
            return
        AnnouncementDetailDialog(tool, announcement_id, self).exec()

    def _show_lecture_detail(self, lecture: dict[str, object]) -> None:
        dialog = LectureDetailDialog(lecture, self)
        dialog.exec()

    def _show_lecture_search_dialog(self) -> None:
        tool = self._require_tool("lecture", "讲座筛选")
        if tool is None:
            return
        LectureSearchDialog(tool, self).exec()

    def _show_reminders_dialog(self) -> None:
        tool = self._require_tool("reminder", "提醒管理")
        if tool is None:
            return
        RemindersDialog(tool, self).exec()

    def _show_calendar_dialog(self) -> None:
        tool = self._require_tool("calendar_reminder", "加入日历提醒")
        if tool is None:
            return
        card = self._cards.get("pku3b_assignments")
        assignments = card.assignments() if isinstance(card, AssignmentTodoCard) else []
        CalendarReminderDialog(tool, assignments, self).exec()

    def _show_memory_dialog(self) -> None:
        tool = self._require_tool("memory", "记忆管理")
        if tool is None:
            return
        MemoryDialog(tool, self, learner=self._memory_learner).exec()

    def _show_knowledge_dialog(self) -> None:
        tool = self._online_tool("knowledge_search")
        if tool is None:
            QMessageBox.information(
                self,
                "知识库检索",
                "知识库检索未开启。请用 --rag 启动，并确认 embedding API key 可用。",
            )
            return
        KnowledgeSearchDialog(tool, self).exec()


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


class AnnouncementsCard(QFrame):
    """Dashboard card for course announcements."""

    detail_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 4

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(220)
        self._items: list[dict[str, object]] = []
        self._expanded = False

        title_label = QLabel("课程通知")
        title_label.setObjectName("CardTitle")
        self._summary_label = QLabel("教学网课程公告")
        self._summary_label.setObjectName("CardBody")
        self._summary_label.setWordWrap(True)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(7)

        self._toggle_button = QPushButton("展开全部")
        self._toggle_button.setObjectName("InlineToggleButton")
        self._toggle_button.clicked.connect(self._toggle_expanded)
        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setObjectName("InlineToggleButton")
        self._refresh_button.clicked.connect(self.refresh_requested)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        actions.addWidget(self._toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._list_host)
        layout.addLayout(actions)
        layout.addStretch()
        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        self._items = []
        self._expanded = False
        self._summary_label.setText(text)
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._summary_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._clear_items()
        self._toggle_button.hide()

    def set_announcements(self, data: dict[str, object]) -> None:
        items = data.get("announcements")
        self._items = (
            [item for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else []
        )
        total = data.get("total_reported")
        if total:
            self._summary_label.setText(f"最近 {len(self._items)} 条 / 总计 {total} 条")
        else:
            self._summary_label.setText(f"最近 {len(self._items)} 条课程通知")
        self._summary_label.setStyleSheet("")
        self._expanded = False
        self._render()

    def _render(self) -> None:
        self._clear_items()
        if not self._items:
            empty = QLabel("暂无课程通知")
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            self._toggle_button.hide()
            return
        visible = self._items if self._expanded else self._items[: self._COLLAPSED_LIMIT]
        for item in visible:
            self._list_layout.addWidget(self._announcement_row(item))
        self._toggle_button.setVisible(len(self._items) > self._COLLAPSED_LIMIT)
        hidden = len(self._items) - len(visible)
        self._toggle_button.setText("收起" if self._expanded else f"展开全部（还有 {hidden} 条）")
        self._list_layout.addStretch()

    def _announcement_row(self, item: dict[str, object]) -> QPushButton:
        course = str(item.get("course") or "未知课程")
        title = str(item.get("title") or "未命名通知")
        button = QPushButton(f"{course}\n{title}")
        button.setObjectName("ListRowButton")
        button.setToolTip("点击查看完整公告")
        announcement_id = str(item.get("id") or "")
        button.clicked.connect(
            lambda _checked=False, value=announcement_id: self.detail_requested.emit(value)
        )
        return button

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._render()

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class TreeholeMessagesCard(QFrame):
    """Dashboard card for PKU Treehole updates."""

    view_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 3

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(196)

        title_label = QLabel("树洞消息")
        title_label.setObjectName("CardTitle")
        self._summary_label = QLabel("关注树洞的新回复")
        self._summary_label.setObjectName("CardBody")
        self._summary_label.setWordWrap(True)

        self._list_host = QWidget()
        self._list_host.setObjectName("TreeholeList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(7)

        self._view_button = QPushButton("查看全部")
        self._view_button.setObjectName("InlineToggleButton")
        self._view_button.clicked.connect(self.view_requested)
        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setObjectName("InlineToggleButton")
        self._refresh_button.clicked.connect(self.refresh_requested)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        actions.addWidget(self._view_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._list_host)
        layout.addLayout(actions)
        layout.addStretch()

        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._summary_label.setText(text)
        self._summary_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._clear_items()

    def set_updates(self, data: dict[str, object]) -> None:
        count = int(data.get("unread_count") or 0)
        message = str(data.get("message") or "暂无树洞新回复")
        status = str(data.get("status") or "ok")
        updates = data.get("updates")
        self._summary_label.setText(message)
        self._summary_label.setStyleSheet(
            "color: #b42318;" if status in {"error", "auth_required", "needs_sms"} else ""
        )
        self._clear_items()
        if not isinstance(updates, list) or not updates:
            empty = QLabel("暂无新回复" if count == 0 and status == "ok" else message)
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            return
        for item in updates[: self._COLLAPSED_LIMIT]:
            if isinstance(item, dict):
                self._list_layout.addWidget(_treehole_row(item))
        hidden = len(updates) - self._COLLAPSED_LIMIT
        if hidden > 0:
            more = QLabel(f"还有 {hidden} 个树洞有更新，点击查看全部")
            more.setObjectName("TodoMore")
            self._list_layout.addWidget(more)
        self._list_layout.addStretch()

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class DeanUpdatesCard(QFrame):
    """Dashboard card for newly surfaced Dean's Office public resources."""

    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 4

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(196)

        title_label = QLabel("教务更新")
        title_label.setObjectName("CardTitle")
        self._summary_label = QLabel("上次检查以来的教务部新内容")
        self._summary_label.setObjectName("CardBody")
        self._summary_label.setWordWrap(True)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(7)

        self._refresh_button = QPushButton("刷新")
        self._refresh_button.setObjectName("InlineToggleButton")
        self._refresh_button.clicked.connect(self.refresh_requested)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._list_host)
        layout.addLayout(actions)
        layout.addStretch()

        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._summary_label.setText(text)
        self._summary_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._clear_items()

    def set_updates(self, data: dict[str, object]) -> None:
        message = str(data.get("message") or "暂无教务部新内容")
        updates = data.get("updates")
        self._summary_label.setText(message)
        self._summary_label.setStyleSheet("")
        self._clear_items()
        if not isinstance(updates, list) or not updates:
            empty = QLabel(message)
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            return
        for item in updates[: self._COLLAPSED_LIMIT]:
            if isinstance(item, dict):
                self._list_layout.addWidget(_dean_update_row(item))
        hidden = len(updates) - self._COLLAPSED_LIMIT
        if hidden > 0:
            more = QLabel(f"还有 {hidden} 条新内容")
            more.setObjectName("TodoMore")
            self._list_layout.addWidget(more)
        self._list_layout.addStretch()

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class PLibMaterialsCard(QFrame):
    """Dashboard card for P-Lib course materials."""

    login_requested = pyqtSignal()
    search_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(196)

        title_label = QLabel("P-Lib 资料")
        title_label.setObjectName("CardTitle")
        self._body_label = QLabel("课程资料检索 · PKUHUB")
        self._body_label.setObjectName("CardBody")
        self._body_label.setWordWrap(True)
        self._quota_label = QLabel("下载额度加载中...")
        self._quota_label.setObjectName("TodoCourse")
        self._quota_label.setWordWrap(True)

        search_button = QPushButton("搜索资料")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self.search_requested)
        login_button = QPushButton("登录")
        login_button.setObjectName("SecondaryButton")
        login_button.clicked.connect(self.login_requested)
        refresh_button = QPushButton("刷新额度")
        refresh_button.setObjectName("InlineToggleButton")
        refresh_button.clicked.connect(self.refresh_requested)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(search_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(login_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._body_label)
        layout.addWidget(self._quota_label)
        layout.addLayout(actions)
        layout.addStretch()

    def set_body(self, text: str, state: str = "data") -> None:
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._body_label.setText(text)
        self._body_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        if state == "loading":
            self._quota_label.setText("正在读取 P-Lib 下载额度...")
        elif state == "error":
            self._quota_label.setText("仍可打开搜索窗口；请确认 plib-cli 已安装并已登录。")

    def set_quota(self, data: dict[str, object]) -> None:
        remaining = data.get("download_remaining")
        if remaining is None:
            self.set_body("已接入 P-Lib 搜索与下载", "data")
            self._quota_label.setText("今日剩余下载次数：未知")
        else:
            self.set_body("已接入 P-Lib 搜索与下载", "data")
            self._quota_label.setText(f"今日剩余下载次数：{remaining}")


class LecturesCard(QFrame):
    """Dashboard card for campus lectures."""

    detail_requested = pyqtSignal(dict)
    search_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 4

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(220)
        self._lectures: list[dict[str, object]] = []
        self._expanded = False

        title_label = QLabel("讲座推荐")
        title_label.setObjectName("CardTitle")
        self._summary_label = QLabel("近期校园讲座")
        self._summary_label.setObjectName("CardBody")
        self._summary_label.setWordWrap(True)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(7)

        self._toggle_button = QPushButton("展开全部")
        self._toggle_button.setObjectName("InlineToggleButton")
        self._toggle_button.clicked.connect(self._toggle_expanded)
        search_button = QPushButton("筛选")
        search_button.setObjectName("InlineToggleButton")
        search_button.clicked.connect(self.search_requested)
        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("InlineToggleButton")
        refresh_button.clicked.connect(self.refresh_requested)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        actions.addWidget(self._toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(search_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._list_host)
        layout.addLayout(actions)
        layout.addStretch()
        self.set_body("加载中...", "loading")

    def set_body(self, text: str, state: str = "data") -> None:
        self._lectures = []
        self._expanded = False
        self._summary_label.setText(text)
        colors = {
            "loading": "#667085",
            "data": "#475467",
            "error": "#b42318",
        }
        self._summary_label.setStyleSheet(f"color: {colors.get(state, colors['data'])};")
        self._clear_items()
        self._toggle_button.hide()

    def set_lectures(self, data: list[object]) -> None:
        self._lectures = [item for item in data if isinstance(item, dict)]
        self._summary_label.setText(f"近期 {len(self._lectures)} 场讲座")
        self._summary_label.setStyleSheet("")
        self._expanded = False
        self._render()

    def _render(self) -> None:
        self._clear_items()
        if not self._lectures:
            empty = QLabel("近期暂无讲座")
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
            self._toggle_button.hide()
            return
        visible = (
            self._lectures
            if self._expanded
            else self._lectures[: self._COLLAPSED_LIMIT]
        )
        for lecture in visible:
            self._list_layout.addWidget(self._lecture_row(lecture))
        self._toggle_button.setVisible(len(self._lectures) > self._COLLAPSED_LIMIT)
        hidden = len(self._lectures) - len(visible)
        self._toggle_button.setText("收起" if self._expanded else f"展开全部（还有 {hidden} 场）")
        self._list_layout.addStretch()

    def _lecture_row(self, lecture: dict[str, object]) -> QPushButton:
        time_text = _lecture_time_text(lecture.get("time"))
        title = str(lecture.get("title") or "未命名讲座")
        location = str(lecture.get("location") or "地点待定")
        button = QPushButton(f"{time_text} · {location}\n{title}")
        button.setObjectName("ListRowButton")
        button.setToolTip("点击查看讲座详情")
        button.clicked.connect(
            lambda _checked=False, item=dict(lecture): self.detail_requested.emit(item)
        )
        return button

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._render()

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class AssignmentTodoCard(QFrame):
    """Dashboard card that renders upcoming assignments as a todo list."""

    add_to_calendar_requested = pyqtSignal()
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

        self._calendar_button = QPushButton("加入日历")
        self._calendar_button.setObjectName("InlineToggleButton")
        self._calendar_button.setToolTip("将勾选的 DDL 加入 macOS 日历并设置系统提醒")
        self._calendar_button.clicked.connect(self.add_to_calendar_requested)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(self._calendar_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        layout.addWidget(self._list_host)
        layout.addLayout(actions)
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

    def assignments(self) -> list[dict[str, object]]:
        """Return the currently loaded assignments (display data for the dialog)."""
        return list(self._assignments)

    def set_calendar_enabled(self, enabled: bool) -> None:
        self._calendar_button.setEnabled(enabled)
        self._calendar_button.setToolTip(
            "将勾选的 DDL 加入 macOS 日历并设置系统提醒"
            if enabled
            else "需在线模式（已注册 calendar_reminder 工具）才能加入日历"
        )

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
        self.setMinimumHeight(300)
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
        self.setMinimumHeight(260)
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

        self.setMinimumHeight(520)
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
            note = str(item.get("note", ""))
            block = CourseBlockWidget(title=title, note=note)
            block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            block.setToolTip(" | ".join(part for part in (detail, note) if part) or title)
            block.clicked.connect(
                lambda course=dict(item): self._show_course_detail(course)
            )
            self._calendar_layout.addWidget(block, start, column, end - start + 1, 1)

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
                f"备注：{course.get('note') or '暂无官方备注'}",
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


class CourseBlockWidget(QFrame):
    """Clickable course cell with a smaller official note line."""

    clicked = pyqtSignal()

    def __init__(self, *, title: str, note: str = "") -> None:
        super().__init__()
        self.setObjectName("CourseBlock")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        title_label = QLabel(title)
        title_label.setObjectName("CourseBlockTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)

        self._note_label = QLabel(note)
        self._note_label.setObjectName("CourseBlockNote")
        self._note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._note_label.setWordWrap(True)
        self._note_label.setVisible(bool(note))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)
        layout.addStretch()
        layout.addWidget(title_label)
        layout.addWidget(self._note_label)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001,N802 - Qt callback.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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


def _treehole_row(item: dict[str, object]) -> QFrame:
    row = ClickableFrame()
    row.setObjectName("TreeholeRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.setToolTip("点击在 Safari 打开树洞")
    row.clicked.connect(lambda: _open_external_url(TREEHOLE_WEB_URL))

    pid = str(item.get("pid") or "?")
    delta = int(item.get("delta") or 0)
    title = QLabel(f"#{pid} · 新增 {delta} 条")
    title.setObjectName("TodoTitle")
    text = QLabel(_clip(str(item.get("text") or "暂无树洞正文摘要"), 72))
    text.setObjectName("TodoCourse")
    text.setWordWrap(True)
    comments = item.get("new_comments")
    first_comment = ""
    if isinstance(comments, list) and comments and isinstance(comments[-1], dict):
        first_comment = str(comments[-1].get("text") or "")
    preview = QLabel(_clip(first_comment, 86) if first_comment else "已检测到回复增长")
    preview.setObjectName("TreeholePreview")
    preview.setWordWrap(True)

    layout = QVBoxLayout(row)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(3)
    layout.addWidget(title)
    layout.addWidget(text)
    layout.addWidget(preview)
    return row


class TreeholeMessagesDialog(QDialog):
    """Modal list of treehole updates opened from the header/card."""

    auth_changed = pyqtSignal()

    def __init__(self, data: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("树洞新消息")
        self.resize(700, 680)
        self._auth = TreeholeAuthService()
        self._pending: object = None

        title = QLabel("树洞新消息")
        title.setObjectName("DialogTitle")
        message = QLabel(str(data.get("message") or "暂无树洞新回复"))
        message.setObjectName("DialogSubtitle")
        message.setWordWrap(True)

        host = QWidget()
        list_layout = QVBoxLayout(host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        updates = data.get("updates")
        if isinstance(updates, list) and updates:
            for item in updates:
                if isinstance(item, dict):
                    list_layout.addWidget(_treehole_detail_row(item))
        else:
            empty = QLabel(str(data.get("message") or "暂无新回复"))
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            list_layout.addWidget(empty)
        list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("TreeholeMessageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        scroll.setMinimumHeight(160)
        scroll.setMaximumHeight(280)

        auth_panel = self._build_auth_panel()

        notify_button = QPushButton("消息通知")
        notify_button.setObjectName("SecondaryButton")
        notify_button.setToolTip("设置 macOS 后台消息通知与检查间隔")
        notify_button.clicked.connect(self._open_notification_settings)
        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        button_row.addWidget(notify_button, 0, Qt.AlignmentFlag.AlignLeft)
        button_row.addStretch()
        button_row.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addWidget(auth_panel)
        layout.addWidget(scroll, 1)
        layout.addLayout(button_row)

        self._refresh_auth_status()

    def _open_notification_settings(self) -> None:
        TreeholeNotificationDialog(parent=self).exec()

    def _build_auth_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("TreeholeAuthPanel")

        title = QLabel("树洞账户")
        title.setObjectName("TreeholeAuthTitle")
        subtitle = QLabel("登录后可直接在首页和对话里查看关注树洞的新回复")
        subtitle.setObjectName("TreeholeAuthSubtitle")
        subtitle.setWordWrap(True)
        self._auth_status = QLabel("正在检查登录状态...")
        self._auth_status.setObjectName("TreeholeAuthStatus")
        self._auth_status.setWordWrap(True)

        self._uid_input = QLineEdit()
        self._uid_input.setPlaceholderText("北大账号 / 学号")
        self._uid_input.setObjectName("TreeholeAuthInput")
        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("密码")
        self._password_input.setObjectName("TreeholeAuthInput")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._sms_input = QLineEdit()
        self._sms_input.setPlaceholderText("短信验证码")
        self._sms_input.setObjectName("TreeholeAuthInput")

        login_button = QPushButton("登录")
        login_button.setObjectName("SecondaryButton")
        login_button.clicked.connect(self._login_treehole)
        send_button = QPushButton("发送验证码")
        send_button.setObjectName("SecondaryButton")
        send_button.clicked.connect(self._send_sms)
        verify_button = QPushButton("完成验证")
        verify_button.setObjectName("PrimaryButton")
        verify_button.clicked.connect(self._verify_sms)
        self._auth_buttons = [login_button, send_button, verify_button]

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)
        header.addWidget(self._auth_status, 0, Qt.AlignmentFlag.AlignTop)

        account_label = QLabel("1 账号登录")
        account_label.setObjectName("TreeholeAuthStep")
        sms_label = QLabel("2 短信验证")
        sms_label.setObjectName("TreeholeAuthStep")

        form = QGridLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(account_label, 0, 0)
        form.addWidget(self._uid_input, 1, 0)
        form.addWidget(self._password_input, 1, 1)
        form.addWidget(login_button, 1, 2)
        form.addWidget(sms_label, 2, 0)
        form.addWidget(self._sms_input, 3, 0)
        form.addWidget(send_button, 3, 1)
        form.addWidget(verify_button, 3, 2)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(form)
        return panel

    def _refresh_auth_status(self) -> None:
        self._auth_status.setText("正在检查登录状态...")
        self._pending = run_async(
            self._auth.status,
            on_done=self._on_auth_status,
            on_error=self._on_auth_status_error,
        )

    def _on_auth_status(self, result: object) -> None:
        data = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        ok = bool(data.get("ok"))
        if ok:
            label = "已登录 · {name}".format(name=data.get("name") or "未知用户")
        else:
            label = str(data.get("message") or "尚未登录树洞")
        self._set_auth_status_text(label, "ok" if ok else "error")

    def _on_auth_status_error(self, message: str) -> None:
        self._set_auth_status_text(f"无法检查登录状态：{message}", "error")

    def _set_auth_status_text(self, text: str, state: str) -> None:
        self._auth_status.setText(text)
        self._auth_status.setProperty("authState", state)
        self._auth_status.style().unpolish(self._auth_status)
        self._auth_status.style().polish(self._auth_status)

    def _login_treehole(self) -> None:
        self._run_auth_action(
            lambda: self._auth.login(
                self._uid_input.text(),
                self._password_input.text(),
            )
        )

    def _send_sms(self) -> None:
        self._run_auth_action(self._auth.send_sms)

    def _verify_sms(self) -> None:
        self._run_auth_action(lambda: self._auth.verify_sms(self._sms_input.text()))

    def _run_auth_action(self, action: Callable[[], dict[str, object]]) -> None:
        self._set_auth_busy(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            action,
            on_done=self._on_auth_action_done,
            on_error=self._on_auth_action_error,
        )

    def _on_auth_action_done(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_auth_busy(False)
        data = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        self._auth_status.setText(str(data.get("message") or "操作完成"))
        if data.get("ok"):
            self.auth_changed.emit()
            self._refresh_auth_status()
        else:
            self._set_auth_status_text(str(data.get("message") or "操作失败"), "error")
            QMessageBox.warning(self, "树洞登录", str(data.get("message") or "操作失败"))

    def _on_auth_action_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_auth_busy(False)
        self._set_auth_status_text(message, "error")
        QMessageBox.warning(self, "树洞登录", message)

    def _set_auth_busy(self, busy: bool) -> None:
        for button in self._auth_buttons:
            button.setEnabled(not busy)


class TreeholeNotificationDialog(QDialog):
    """Enable/disable macOS desktop notifications for treehole replies and set
    the background poll interval.

    Drives `TreeholeNotificationService`, which manages a per-user LaunchAgent.
    macOS-only: off macOS (or without the treehole binary) the controls disable
    with an explanatory status. launchctl calls block, so they run via
    `run_async`; the file-only `status()` is read inline.
    """

    _INTERVAL_PRESETS = [
        ("每 1 分钟", 60),
        ("每 5 分钟", 300),
        ("每 10 分钟", 600),
        ("每 30 分钟", 1800),
        ("每 1 小时", 3600),
    ]

    def __init__(
        self,
        service: TreeholeNotificationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("树洞消息通知")
        self.resize(560, 380)
        self._service = service if service is not None else TreeholeNotificationService()
        self._pending: object = None

        title = QLabel("树洞消息通知")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("在 macOS 后台定时检查关注的树洞，有新回复时推送系统通知。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._status_label = QLabel("正在检查通知状态...")
        self._status_label.setObjectName("TreeholeAuthStatus")
        self._status_label.setWordWrap(True)

        interval_label = QLabel("检查间隔")
        interval_label.setObjectName("TreeholeAuthStep")
        self._interval_combo = QComboBox()
        for text, value in self._INTERVAL_PRESETS:
            self._interval_combo.addItem(text, value)

        self._enable_button = QPushButton("开启通知")
        self._enable_button.setObjectName("PrimaryButton")
        self._enable_button.clicked.connect(self._enable)
        self._disable_button = QPushButton("关闭通知")
        self._disable_button.setObjectName("SecondaryButton")
        self._disable_button.clicked.connect(self._disable)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        self._action_buttons = [self._enable_button, self._disable_button]

        note = QLabel(
            "首次通知前需在「系统设置 › 通知」中允许“Script Editor”发送通知；"
            "通知由 osascript 发送，会显示为 Script Editor 图标。后台进程独立于本应用运行，"
            "关闭窗口后仍会按间隔检查。"
        )
        note.setObjectName("CardBody")
        note.setWordWrap(True)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        controls.addWidget(interval_label)
        controls.addWidget(self._interval_combo, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        buttons.addWidget(self._enable_button)
        buttons.addWidget(self._disable_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._status_label)
        layout.addLayout(controls)
        layout.addWidget(note)
        layout.addStretch()
        layout.addLayout(buttons)

        self._refresh_status()

    def _refresh_status(self) -> None:
        self._apply_status(self._service.status())

    def _apply_status(self, status: dict[str, object]) -> None:
        supported = bool(status.get("supported"))
        binary = bool(status.get("binary_available"))
        enabled = bool(status.get("enabled"))
        message = str(status.get("message") or "")
        if supported and binary and not status.get("logged_in"):
            message += "\n尚未登录树洞，后台通知将无法获取消息，请先在「树洞账户」中登录。"
        if enabled:
            state = "ok"
        elif not (supported and binary):
            state = "error"
        else:
            state = ""
        self._set_status_text(message, state)
        self._select_interval(int(status.get("interval") or DEFAULT_NOTIFY_INTERVAL))

        can_configure = supported and binary
        self._interval_combo.setEnabled(can_configure)
        self._enable_button.setEnabled(can_configure)
        self._enable_button.setText("更新设置" if enabled else "开启通知")
        self._disable_button.setEnabled(supported and enabled)

    def _set_status_text(self, text: str, state: str) -> None:
        self._status_label.setText(text)
        self._status_label.setProperty("authState", state)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _select_interval(self, value: int) -> None:
        index = self._interval_combo.findData(value)
        if index < 0:
            self._interval_combo.addItem(f"每 {value} 秒", value)
            index = self._interval_combo.findData(value)
        self._interval_combo.setCurrentIndex(index)

    def _enable(self) -> None:
        interval = int(self._interval_combo.currentData())
        self._run_action(lambda: self._service.enable(interval))

    def _disable(self) -> None:
        self._run_action(self._service.disable)

    def _run_action(self, action: Callable[[], dict[str, object]]) -> None:
        self._set_busy(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            action,
            on_done=self._on_action_done,
            on_error=self._on_action_error,
        )

    def _on_action_done(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        data = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        self._refresh_status()
        if not data.get("ok"):
            QMessageBox.warning(self, "树洞消息通知", str(data.get("message") or "操作失败"))
        elif data.get("message"):
            self._set_status_text(str(data["message"]), "ok")

    def _on_action_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        self._refresh_status()
        QMessageBox.warning(self, "树洞消息通知", message)

    def _set_busy(self, busy: bool) -> None:
        for button in self._action_buttons:
            button.setEnabled(not busy)
        self._interval_combo.setEnabled(not busy)


class PLibSearchDialog(QDialog):
    """Search and download P-Lib materials without leaving the GUI."""

    _TYPES = ["全部", "习题", "其他", "汇编", "笔记", "答案", "试卷", "课件", "课本"]
    _SORTS = [
        ("相关度", "relevance"),
        ("最新上传", "newest"),
        ("下载最多", "downloads"),
        ("浏览最多", "views"),
        ("收藏最多", "likes"),
        ("标题", "title"),
        ("评论最多", "comments"),
    ]
    _TIMES = [
        ("全部时间", "all"),
        ("最近一周", "week"),
        ("最近一月", "month"),
        ("最近一年", "year"),
    ]

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("P-Lib 资料搜索")
        self.resize(820, 680)
        self._tool = tool
        self._results: list[dict[str, object]] = []
        self._pending: object = None

        title = QLabel("P-Lib 资料搜索")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("搜索 PKUHUB 课程资料；下载会保存到本项目 downloads/plib 目录。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("输入课程名、资料名或关键词")
        self._query_input.returnPressed.connect(self._search)
        self._type_combo = QComboBox()
        self._type_combo.addItems(self._TYPES)
        self._sort_combo = QComboBox()
        for label, value in self._SORTS:
            self._sort_combo.addItem(label, value)
        self._time_combo = QComboBox()
        for label, value in self._TIMES:
            self._time_combo.addItem(label, value)
        self._limit_combo = QComboBox()
        self._limit_combo.addItems(["10", "20", "30"])

        self._search_button = QPushButton("搜索")
        self._search_button.setObjectName("PrimaryButton")
        self._search_button.clicked.connect(self._search)
        self._detail_button = QPushButton("查看详情")
        self._detail_button.setObjectName("SecondaryButton")
        self._detail_button.clicked.connect(self._show_selected)
        self._download_button = QPushButton("下载选中")
        self._download_button.setObjectName("SecondaryButton")
        self._download_button.clicked.connect(self._download_selected)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)

        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(8)
        filters.addWidget(self._query_input, 0, 0, 1, 4)
        filters.addWidget(self._type_combo, 1, 0)
        filters.addWidget(self._sort_combo, 1, 1)
        filters.addWidget(self._time_combo, 1, 2)
        filters.addWidget(self._limit_combo, 1, 3)
        filters.addWidget(self._search_button, 1, 4)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(2, 1)
        filters.setColumnStretch(3, 1)

        self._status_label = QLabel("输入关键词后开始搜索")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)

        self._result_list = QListWidget()
        self._result_list.setObjectName("PLibResultList")
        self._result_list.itemDoubleClicked.connect(lambda _item: self._show_selected())
        self._result_list.currentItemChanged.connect(self._on_selection_changed)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(self._detail_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(self._download_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()
        actions.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(filters)
        layout.addWidget(self._status_label)
        layout.addWidget(self._result_list, 1)
        layout.addLayout(actions)
        self._set_selected_actions(False)

    def _run_tool(self, args: dict[str, object], on_success: Callable[[object], None]) -> None:
        """Invoke the P-Lib tool off the GUI thread, then run on_success."""
        self._set_busy(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._on_success: Callable[[object], None] | None = on_success
        self._pending = run_async(
            lambda: self._tool.invoke(args),
            on_done=self._on_tool_done,
            on_error=self._on_tool_error,
        )

    def _on_tool_done(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        callback, self._on_success = self._on_success, None
        if callback is not None:
            callback(result)

    def _on_tool_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        self._on_success = None
        self._status_label.setStyleSheet("color: #b42318;")
        self._status_label.setText(f"操作失败：{message}")

    def _search(self) -> None:
        query = self._query_input.text().strip()
        if not query:
            QMessageBox.warning(self, "P-Lib 搜索", "请输入搜索关键词。")
            return
        args: dict[str, object] = {
            "action": "search",
            "query": query,
            "sort": self._sort_combo.currentData(),
            "limit": int(self._limit_combo.currentText()),
        }
        material_type = self._type_combo.currentText()
        if material_type != "全部":
            args["type"] = material_type
        time_value = str(self._time_combo.currentData() or "")
        if time_value != "all":
            args["time"] = time_value
        self._run_tool(args, self._on_search_result)

    def _on_search_result(self, result: object) -> None:
        if not getattr(result, "success", False):
            self._status_label.setStyleSheet("color: #b42318;")
            self._status_label.setText(f"搜索失败：{getattr(result, 'error', '')}")
            return
        data = result.data if isinstance(result.data, dict) else {}
        results = data.get("results")
        self._results = (
            [item for item in results if isinstance(item, dict)]
            if isinstance(results, list)
            else []
        )
        self._render_results(data)

    def _render_results(self, data: dict[str, object]) -> None:
        self._result_list.clear()
        self._set_selected_actions(False)
        total = data.get("total")
        count = len(self._results)
        self._status_label.setStyleSheet("")
        self._status_label.setText(f"找到 {count} 条结果" + (f" / 总计 {total}" if total else ""))
        if not self._results:
            item = QListWidgetItem("暂无匹配资料")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._result_list.addItem(item)
            return
        for material in self._results:
            item = QListWidgetItem(_plib_item_text(material))
            item.setData(Qt.ItemDataRole.UserRole, material)
            item.setToolTip(str(material.get("description") or material.get("title") or ""))
            self._result_list.addItem(item)
        self._result_list.setCurrentRow(0)

    def _show_selected(self) -> None:
        material = self._selected_material()
        material_id = _material_id(material)
        if material_id is None:
            return
        self._run_tool(
            {"action": "show", "id": material_id},
            lambda result: self._on_show_result(result, material),
        )

    def _on_show_result(self, result: object, material: dict[str, object]) -> None:
        if not getattr(result, "success", False):
            error = str(getattr(result, "error", "") or "获取详情失败")
            QMessageBox.warning(self, "P-Lib 详情", error)
            return
        detail = result.data if isinstance(result.data, dict) else material
        QMessageBox.information(self, "P-Lib 详情", _plib_detail_text(detail))

    def _download_selected(self) -> None:
        material = self._selected_material()
        material_id = _material_id(material)
        if material_id is None:
            return
        title = str(material.get("title") or f"资料 {material_id}")
        reply = QMessageBox.question(
            self,
            "下载 P-Lib 资料",
            f"确定下载：{title}\n\n文件将保存到 downloads/plib。",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_tool({"action": "download", "id": material_id}, self._on_download_result)

    def _on_download_result(self, result: object) -> None:
        if not getattr(result, "success", False):
            QMessageBox.warning(self, "P-Lib 下载", str(getattr(result, "error", "") or "下载失败"))
            return
        data = result.data if isinstance(result.data, dict) else {}
        QMessageBox.information(self, "P-Lib 下载", _plib_download_text(data))

    def _selected_material(self) -> dict[str, object]:
        item = self._result_list.currentItem()
        if item is None:
            return {}
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else {}

    def _on_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        has_material = current is not None and _material_id(self._selected_material()) is not None
        self._set_selected_actions(has_material)

    def _set_selected_actions(self, enabled: bool) -> None:
        self._detail_button.setEnabled(enabled)
        self._download_button.setEnabled(enabled)

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self._query_input,
            self._type_combo,
            self._sort_combo,
            self._time_combo,
            self._limit_combo,
            self._search_button,
            self._result_list,
        ):
            widget.setEnabled(not busy)


class PLibLoginDialog(QDialog):
    """P-Lib login dialog backed by the local plib CLI."""

    auth_changed = pyqtSignal()

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("P-Lib 登录")
        self.resize(560, 330)
        self._tool = tool
        self._pending: object = None

        title = QLabel("P-Lib 登录")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("登录后可在 GUI 中搜索、查看详情并下载 PKUHUB 课程资料。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        panel = QFrame()
        panel.setObjectName("PLibAuthPanel")
        self._status_label = QLabel("请输入 P-Lib 邮箱和密码")
        self._status_label.setObjectName("PLibAuthStatus")
        self._status_label.setWordWrap(True)

        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText("邮箱")
        self._email_input.setObjectName("TreeholeAuthInput")
        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("密码")
        self._password_input.setObjectName("TreeholeAuthInput")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.returnPressed.connect(self._login)

        self._login_button = QPushButton("登录")
        self._login_button.setObjectName("PrimaryButton")
        self._login_button.clicked.connect(self._login)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(self._email_input, 0, 0, 1, 2)
        form.addWidget(self._password_input, 1, 0, 1, 2)
        form.addWidget(self._login_button, 2, 0)
        form.setColumnStretch(1, 1)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(12)
        panel_layout.addWidget(self._status_label)
        panel_layout.addLayout(form)

        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(panel)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

    def _login(self) -> None:
        email = self._email_input.text().strip()
        password = self._password_input.text()
        if not email or not password:
            QMessageBox.warning(self, "P-Lib 登录", "请输入邮箱和密码。")
            return
        self._set_busy(True)
        self._set_status("正在登录 P-Lib...", "pending")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            lambda: self._tool.invoke(
                {"action": "login", "email": email, "password": password}
            ),
            on_done=self._on_login_result,
            on_error=self._on_login_error,
        )

    def _on_login_result(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        if not getattr(result, "success", False):
            error = str(getattr(result, "error", "") or "登录失败")
            self._set_status(error, "error")
            QMessageBox.warning(self, "P-Lib 登录", error)
            return
        data = result.data if isinstance(result.data, dict) else {}
        remaining = data.get("quota_remaining", data.get("download_remaining"))
        message = "登录成功"
        if remaining is not None:
            message += f" · 今日剩余下载次数：{remaining}"
        self._set_status(message, "ok")
        self.auth_changed.emit()

    def _on_login_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        self._set_status(message, "error")
        QMessageBox.warning(self, "P-Lib 登录", message)

    def _set_busy(self, busy: bool) -> None:
        self._email_input.setEnabled(not busy)
        self._password_input.setEnabled(not busy)
        self._login_button.setEnabled(not busy)

    def _set_status(self, text: str, state: str) -> None:
        self._status_label.setText(text)
        self._status_label.setProperty("authState", state)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)


class AnnouncementDetailDialog(QDialog):
    """Fetch and display one course announcement."""

    def __init__(
        self, tool: Tool, announcement_id: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("课程通知详情")
        self.resize(720, 620)
        self._tool = tool
        self._pending: object = None

        title = QLabel("课程通知详情")
        title.setObjectName("DialogTitle")
        self._subtitle = QLabel(f"公告 ID：{announcement_id}")
        self._subtitle.setObjectName("DialogSubtitle")
        self._subtitle.setWordWrap(True)

        self._body_label = QLabel("正在加载公告详情...")
        self._body_label.setObjectName("DialogBody")
        self._body_label.setWordWrap(True)
        self._body_label.setTextInteractionFlags(
            self._body_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )

        scroll = QScrollArea()
        scroll.setObjectName("DetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(10, 10, 10, 10)
        host_layout.addWidget(self._body_label)
        host_layout.addStretch()
        scroll.setWidget(host)

        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addWidget(scroll, 1)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self._load_detail(announcement_id)

    def _load_detail(self, announcement_id: str) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            lambda: self._tool.invoke({"announcement_id": announcement_id}),
            on_done=self._on_detail_loaded,
            on_error=self._on_detail_error,
        )

    def _on_detail_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._body_label.setStyleSheet("color: #b42318;")
        self._body_label.setText(f"公告详情加载失败：{message}")

    def _on_detail_loaded(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        if not getattr(result, "success", False):
            self._body_label.setText(str(getattr(result, "error", "") or "公告详情加载失败"))
            self._body_label.setStyleSheet("color: #b42318;")
            return
        data = result.data if isinstance(result.data, dict) else {}
        announcement = data.get("announcement")
        if not isinstance(announcement, dict):
            self._body_label.setText("公告详情格式异常")
            self._body_label.setStyleSheet("color: #b42318;")
            return
        self._subtitle.setText(
            "{course} · {posted}".format(
                course=announcement.get("course") or "未知课程",
                posted=announcement.get("posted_at") or "发布时间未知",
            )
        )
        self._body_label.setText(_announcement_detail_text(announcement))


class LectureDetailDialog(QDialog):
    """Display one lecture and optionally open its source link."""

    def __init__(self, lecture: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("讲座详情")
        self.resize(640, 420)
        self._link = str(lecture.get("link") or "")

        title = QLabel(str(lecture.get("title") or "未命名讲座"))
        title.setObjectName("DialogTitle")
        subtitle = QLabel(_lecture_time_text(lecture.get("time")))
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        body = QLabel(_lecture_detail_text(lecture))
        body.setObjectName("DialogBody")
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            body.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )

        open_button = QPushButton("打开链接")
        open_button.setObjectName("SecondaryButton")
        open_button.setEnabled(bool(self._link))
        open_button.clicked.connect(self._open_link)
        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addStretch()
        actions.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(body, 1)
        layout.addLayout(actions)

    def _open_link(self) -> None:
        if self._link:
            _open_external_url(self._link)


class LectureSearchDialog(QDialog):
    """Filter lectures through the existing LectureTool."""

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("讲座筛选")
        self.resize(760, 620)
        self._tool = tool
        self._lectures: list[dict[str, object]] = []

        title = QLabel("讲座筛选")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("按关键词和日期范围筛选仓库内讲座数据。")
        subtitle.setObjectName("DialogSubtitle")

        self._keyword_input = QLineEdit()
        self._keyword_input.setPlaceholderText("关键词：标题、主讲人或地点")
        self._start_input = QLineEdit()
        self._start_input.setPlaceholderText("开始日期 YYYY-MM-DD")
        self._end_input = QLineEdit()
        self._end_input.setPlaceholderText("结束日期 YYYY-MM-DD")
        self._limit_combo = QComboBox()
        self._limit_combo.addItems(["5", "10", "20"])
        search_button = QPushButton("筛选")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self._search)

        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(8)
        filters.addWidget(self._keyword_input, 0, 0, 1, 4)
        filters.addWidget(self._start_input, 1, 0)
        filters.addWidget(self._end_input, 1, 1)
        filters.addWidget(self._limit_combo, 1, 2)
        filters.addWidget(search_button, 1, 3)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)

        self._status_label = QLabel("点击筛选查看结果")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)
        self._result_list = QListWidget()
        self._result_list.setObjectName("PLibResultList")
        self._result_list.itemDoubleClicked.connect(lambda _item: self._open_selected())

        detail_button = QPushButton("查看详情")
        detail_button.setObjectName("SecondaryButton")
        detail_button.clicked.connect(self._open_selected)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(detail_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(filters)
        layout.addWidget(self._status_label)
        layout.addWidget(self._result_list, 1)
        layout.addLayout(actions)
        self._search()

    def _search(self) -> None:
        args: dict[str, object] = {"limit": int(self._limit_combo.currentText())}
        keyword = self._keyword_input.text().strip()
        if keyword:
            args["keyword"] = keyword
        start = self._start_input.text().strip()
        if start:
            args["start_date"] = start
        end = self._end_input.text().strip()
        if end:
            args["end_date"] = end
        result = self._tool.invoke(args)
        if not result.success:
            self._status_label.setText(str(result.error or "筛选失败"))
            self._status_label.setStyleSheet("color: #b42318;")
            return
        data = result.data if isinstance(result.data, list) else []
        self._lectures = [item for item in data if isinstance(item, dict)]
        self._render_results()

    def _render_results(self) -> None:
        self._result_list.clear()
        self._status_label.setStyleSheet("")
        self._status_label.setText(f"找到 {len(self._lectures)} 场讲座")
        if not self._lectures:
            item = QListWidgetItem("暂无匹配讲座")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._result_list.addItem(item)
            return
        for lecture in self._lectures:
            item = QListWidgetItem(
                "{time} · {location}\n{title}".format(
                    time=_lecture_time_text(lecture.get("time")),
                    location=lecture.get("location") or "地点待定",
                    title=lecture.get("title") or "未命名讲座",
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, lecture)
            self._result_list.addItem(item)
        self._result_list.setCurrentRow(0)

    def _open_selected(self) -> None:
        item = self._result_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            LectureDetailDialog(data, self).exec()


class RemindersDialog(QDialog):
    """Manage reminders stored by ReminderTool."""

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("提醒管理")
        self.resize(760, 620)
        self._tool = tool
        self._items: list[dict[str, object]] = []

        title = QLabel("提醒管理")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("这里管理本地提醒列表；当前版本不会触发 macOS 系统通知。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("提醒内容")
        self._time_input = QLineEdit()
        self._time_input.setPlaceholderText("触发时间，例如 2026-06-02T18:00:00")
        add_button = QPushButton("新增")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(self._text_input, 0, 0, 1, 2)
        form.addWidget(self._time_input, 1, 0)
        form.addWidget(add_button, 1, 1)
        form.setColumnStretch(0, 1)

        self._status_label = QLabel("加载提醒中...")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)
        self._list = QListWidget()
        self._list.setObjectName("PLibResultList")

        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self._load)
        done_button = QPushButton("标记完成")
        done_button.setObjectName("SecondaryButton")
        done_button.clicked.connect(self._done)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("SecondaryButton")
        delete_button.clicked.connect(self._delete)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(refresh_button)
        actions.addWidget(done_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(self._list, 1)
        layout.addLayout(actions)
        self._load()

    def _load(self) -> None:
        result = self._tool.invoke(
            {"action": "list", "pending_only": False, "future_only": False}
        )
        if not result.success:
            self._status_label.setText(str(result.error or "提醒读取失败"))
            self._status_label.setStyleSheet("color: #b42318;")
            return
        data = result.data if isinstance(result.data, list) else []
        self._items = [item for item in data if isinstance(item, dict)]
        self._render()

    def _render(self) -> None:
        self._list.clear()
        self._status_label.setStyleSheet("")
        pending = sum(1 for item in self._items if not item.get("done"))
        self._status_label.setText(f"共 {len(self._items)} 条提醒，未完成 {pending} 条")
        if not self._items:
            empty = QListWidgetItem("暂无提醒")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            return
        for reminder in self._items:
            done = "已完成" if reminder.get("done") else "未完成"
            item = QListWidgetItem(
                "#{id} · {done} · {time}\n{text}".format(
                    id=reminder.get("id", "?"),
                    done=done,
                    time=reminder.get("trigger_time") or "时间未知",
                    text=reminder.get("text") or "",
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, reminder)
            self._list.addItem(item)

    def _add(self) -> None:
        text = self._text_input.text().strip()
        trigger_time = self._time_input.text().strip()
        result = self._tool.invoke(
            {"action": "add", "text": text, "trigger_time": trigger_time}
        )
        if not result.success:
            QMessageBox.warning(self, "提醒管理", str(result.error or "新增失败"))
            return
        self._text_input.clear()
        self._time_input.clear()
        self._load()

    def _done(self) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            return
        result = self._tool.invoke({"action": "done", "id": reminder_id})
        if not result.success:
            QMessageBox.warning(self, "提醒管理", str(result.error or "操作失败"))
            return
        self._load()

    def _delete(self) -> None:
        reminder_id = self._selected_id()
        if reminder_id is None:
            return
        reply = QMessageBox.question(self, "删除提醒", f"确定删除提醒 #{reminder_id}？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._tool.invoke({"action": "delete", "id": reminder_id})
        if not result.success:
            QMessageBox.warning(self, "提醒管理", str(result.error or "删除失败"))
            return
        self._load()

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return None
        value = data.get("id")
        return value if isinstance(value, int) else None


class CalendarReminderDialog(QDialog):
    """Selectively push upcoming DDLs into macOS Calendar via CalendarReminderTool.

    Seeded from the assignment card's already-loaded data (display only — no
    refetch). The add shells to ``osascript`` and blocks, so it runs through
    ``run_async`` to keep the window responsive.
    """

    _ALARM_OPTIONS = (
        ("事件发生时提醒", 0),
        ("提前 1 小时", 60),
        ("提前 1 天", 1440),
        ("提前 2 天", 2880),
    )
    _DEFAULT_ALARM_INDEX = 2  # 提前 1 天

    def __init__(
        self,
        tool: Tool,
        assignments: list[dict[str, object]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("加入日历提醒")
        self.resize(720, 620)
        self._tool = tool
        self._pending: object = None
        self._entries = _calendar_candidates(assignments or [])

        title = QLabel("加入 macOS 日历提醒")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "勾选要添加的 DDL，将写入『PKU Captain』日历并设置系统提醒（到点会有 macOS 通知）。"
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._alarm_combo = QComboBox()
        for label, minutes in self._ALARM_OPTIONS:
            self._alarm_combo.addItem(label, minutes)
        self._alarm_combo.setCurrentIndex(self._DEFAULT_ALARM_INDEX)
        alarm_row = QHBoxLayout()
        alarm_row.setContentsMargins(0, 0, 0, 0)
        alarm_row.setSpacing(10)
        alarm_label = QLabel("提醒时间")
        alarm_label.setObjectName("CardBody")
        alarm_row.addWidget(alarm_label, 0, Qt.AlignmentFlag.AlignLeft)
        alarm_row.addWidget(self._alarm_combo, 0, Qt.AlignmentFlag.AlignLeft)
        alarm_row.addStretch()

        self._list = QListWidget()
        self._list.setObjectName("PLibResultList")
        for entry in self._entries:
            item = QListWidgetItem(str(entry["label"]))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)

        self._status_label = QLabel("")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)

        select_all = QPushButton("全选")
        select_all.setObjectName("SecondaryButton")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = QPushButton("全不选")
        select_none.setObjectName("SecondaryButton")
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        self._add_button = QPushButton("添加选中")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.clicked.connect(self._add_selected)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(select_all)
        actions.addWidget(select_none)
        actions.addStretch()
        actions.addWidget(self._add_button)
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(alarm_row)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._status_label)
        layout.addLayout(actions)

        if not self._entries:
            self._status_label.setText("近期没有带截止时间的未完成作业可添加。")
            self._add_button.setEnabled(False)
            select_all.setEnabled(False)
            select_none.setEnabled(False)
        else:
            self._status_label.setText(f"共 {len(self._entries)} 个可添加的 DDL。")

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)

    def _checked_entries(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict):
                result.append(entry)
        return result

    def _add_selected(self) -> None:
        entries = self._checked_entries()
        if not entries:
            self._status_label.setText("请先勾选要添加的 DDL。")
            return
        alarm_minutes = self._alarm_combo.currentData()
        payload = [
            {
                "title": str(entry["summary"]),
                "deadline_iso": str(entry["deadline_iso"]),
                "notes": str(entry.get("notes") or ""),
            }
            for entry in entries
        ]
        self._set_busy(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            lambda: self._tool.invoke(
                {"items": payload, "alarm_minutes_before": alarm_minutes}
            ),
            on_done=self._on_added,
            on_error=self._on_add_error,
        )

    def _on_added(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        success = bool(getattr(result, "success", False))
        data = getattr(result, "data", None)
        data = data if isinstance(data, dict) else {}
        added = data.get("added") if isinstance(data.get("added"), list) else []
        failed = data.get("failed") if isinstance(data.get("failed"), list) else []
        calendar = str(data.get("calendar") or "PKU Captain")

        added_titles = {
            str(item.get("title"))
            for item in added
            if isinstance(item, dict)
        }
        self._mark_added(added_titles)

        if not success:
            message = str(getattr(result, "error", None) or "添加失败。")
            self._status_label.setText(message)
            self._status_label.setStyleSheet("color: #b42318;")
            QMessageBox.warning(self, "加入日历提醒", message)
            return

        self._status_label.setStyleSheet("")
        summary = f"已向『{calendar}』添加 {len(added)} 个 DDL 提醒"
        if failed:
            summary += f"，{len(failed)} 个失败"
        self._status_label.setText(summary + "。")
        QMessageBox.information(self, "加入日历提醒", summary + "。")

    def _on_add_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_busy(False)
        self._status_label.setText(f"添加失败：{message}")
        self._status_label.setStyleSheet("color: #b42318;")
        QMessageBox.warning(self, "加入日历提醒", message)

    def _mark_added(self, added_titles: set[str]) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(entry, dict) or str(entry.get("summary")) not in added_titles:
                continue
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setText(f"✓ 已添加 · {entry.get('label')}")

    def _set_busy(self, busy: bool) -> None:
        self._add_button.setEnabled(not busy)
        self._add_button.setText("添加中..." if busy else "添加选中")


class MemoryDialog(QDialog):
    """Inspect and edit persistent user preferences."""

    def __init__(
        self,
        tool: Tool,
        parent: QWidget | None = None,
        learner: MemoryLearnService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("记忆管理")
        self.resize(760, 620)
        self._tool = tool
        self._learner = learner
        self._items: list[dict[str, object]] = []
        self._pending: object = None

        title = QLabel("记忆管理")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "用自然语言记下任何信息，自动整理并保存为长期记忆；对话里提到的偏好也会被自动记住。"
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText(
            "例如：我住在燕园，喜欢用中文交流，周三下午有空"
        )
        self._note_input.returnPressed.connect(self._remember)
        self._remember_button = QPushButton("记住")
        self._remember_button.setObjectName("PrimaryButton")
        self._remember_button.clicked.connect(self._remember)
        remember_button = self._remember_button
        form = QHBoxLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.addWidget(self._note_input, 1)
        form.addWidget(remember_button)

        self._status_label = QLabel("加载记忆中...")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)
        self._list = QListWidget()
        self._list.setObjectName("PLibResultList")
        self._list.itemDoubleClicked.connect(lambda _item: self._fill_selected())

        refresh_button = QPushButton("刷新")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self._load)
        edit_button = QPushButton("填入编辑")
        edit_button.setObjectName("SecondaryButton")
        edit_button.clicked.connect(self._fill_selected)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("SecondaryButton")
        delete_button.clicked.connect(self._delete)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(refresh_button)
        actions.addWidget(edit_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(self._list, 1)
        layout.addLayout(actions)
        self._load()

    def _load(self) -> None:
        result = self._tool.invoke({"action": "list"})
        if not result.success:
            self._status_label.setText(str(result.error or "记忆读取失败"))
            self._status_label.setStyleSheet("color: #b42318;")
            return
        data = result.data if isinstance(result.data, list) else []
        self._items = [item for item in data if isinstance(item, dict)]
        self._render()

    def _render(self) -> None:
        self._list.clear()
        self._status_label.setStyleSheet("")
        self._status_label.setText(f"共 {len(self._items)} 条记忆")
        if not self._items:
            empty = QListWidgetItem("暂无记忆")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            return
        for memory in self._items:
            # Value first — it carries the meaning; the key is an internal
            # handle (auto-derived for free-text notes), shown muted below.
            item = QListWidgetItem(
                "{value}\n  {key}".format(
                    value=memory.get("value") or "",
                    key=memory.get("key") or "",
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, memory)
            self._list.addItem(item)

    def _remember(self) -> None:
        text = self._note_input.text().strip()
        if not text:
            return
        if self._learner is None:
            # No LLM available (offline): store the sentence verbatim. Local
            # file write, so it is instant — no need for a worker thread.
            result = self._tool.invoke({"action": "remember", "text": text})
            if not result.success:
                QMessageBox.warning(self, "记忆管理", str(result.error or "保存失败"))
                return
            self._note_input.clear()
            self._load()
            return
        # Online: let the LLM split the sentence into clean facts. This is a
        # network call, so run it off the GUI thread.
        self._set_busy(True)
        learner = self._learner
        self._pending = run_async(
            lambda: learner.learn(text),
            on_done=self._on_learn_done,
            on_error=self._on_learn_error,
        )

    def _set_busy(self, busy: bool) -> None:
        self._remember_button.setEnabled(not busy)
        self._remember_button.setText("整理中..." if busy else "记住")
        self._note_input.setEnabled(not busy)

    def _on_learn_done(self, result: object) -> None:
        self._set_busy(False)
        stored = list(getattr(result, "stored", []) or [])
        self._note_input.clear()
        self._load()
        if stored:
            self._status_label.setStyleSheet("")
            self._status_label.setText(f"已记住 {len(stored)} 条：{'；'.join(stored)}")

    def _on_learn_error(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.warning(self, "记忆管理", f"保存失败：{message}")

    def _fill_selected(self) -> None:
        memory = self._selected_memory()
        if not memory:
            return
        # Re-saving edited text stores a fresh entry; the original stays
        # until deleted from the list (free-text notes don't overwrite).
        self._note_input.setText(str(memory.get("value") or ""))

    def _delete(self) -> None:
        memory = self._selected_memory()
        key = str(memory.get("key") or "")
        if not key:
            return
        reply = QMessageBox.question(self, "删除记忆", f"确定删除记忆 {key!r}？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._tool.invoke({"action": "delete", "key": key})
        if not result.success:
            QMessageBox.warning(self, "记忆管理", str(result.error or "删除失败"))
            return
        self._load()

    def _selected_memory(self) -> dict[str, object]:
        item = self._list.currentItem()
        if item is None:
            return {}
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else {}


class KnowledgeSearchDialog(QDialog):
    """Manual RAG search panel for KnowledgeSearchTool."""

    def __init__(self, tool: Tool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("知识库检索")
        self.resize(820, 680)
        self._tool = tool
        self._hits: list[dict[str, object]] = []
        self._pending: object = None

        title = QLabel("知识库检索")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("检索已索引的教务、校历等知识库片段。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("输入检索问题或关键词")
        self._query_input.returnPressed.connect(self._search)
        self._top_k_combo = QComboBox()
        self._top_k_combo.addItems(["5", "10", "20"])
        search_button = QPushButton("搜索")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self._search)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.addWidget(self._query_input, 0, 0)
        form.addWidget(self._top_k_combo, 0, 1)
        form.addWidget(search_button, 0, 2)
        form.setColumnStretch(0, 1)

        self._status_label = QLabel("输入关键词后开始搜索")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)
        self._result_list = QListWidget()
        self._result_list.setObjectName("PLibResultList")
        self._result_list.itemDoubleClicked.connect(lambda _item: self._show_selected())

        detail_button = QPushButton("查看片段")
        detail_button.setObjectName("SecondaryButton")
        detail_button.clicked.connect(self._show_selected)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(detail_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(self._result_list, 1)
        layout.addLayout(actions)

    def _search(self) -> None:
        query = self._query_input.text().strip()
        if not query:
            QMessageBox.warning(self, "知识库检索", "请输入检索关键词。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._status_label.setStyleSheet("")
        self._status_label.setText("检索中...")
        self._pending = run_async(
            lambda: self._tool.invoke(
                {"query": query, "top_k": int(self._top_k_combo.currentText())}
            ),
            on_done=self._on_search_result,
            on_error=self._on_search_error,
        )

    def _on_search_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._status_label.setStyleSheet("color: #b42318;")
        self._status_label.setText(f"检索失败：{message}")

    def _on_search_result(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        if not getattr(result, "success", False):
            self._status_label.setText(str(getattr(result, "error", "") or "检索失败"))
            self._status_label.setStyleSheet("color: #b42318;")
            return
        data = result.data if isinstance(result.data, list) else []
        self._hits = [item for item in data if isinstance(item, dict)]
        self._render()

    def _render(self) -> None:
        self._result_list.clear()
        self._status_label.setStyleSheet("")
        self._status_label.setText(f"返回 {len(self._hits)} 条片段")
        if not self._hits:
            empty = QListWidgetItem("暂无匹配片段")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._result_list.addItem(empty)
            return
        for index, hit in enumerate(self._hits, start=1):
            item = QListWidgetItem(
                "{index}. {source} / {identifier} · score {score:.3f}\n{text}".format(
                    index=index,
                    source=hit.get("source") or "unknown",
                    identifier=hit.get("identifier") or "",
                    score=float(hit.get("score") or 0),
                    text=_clip(str(hit.get("text") or ""), 110),
                )
            )
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self._result_list.addItem(item)
        self._result_list.setCurrentRow(0)

    def _show_selected(self) -> None:
        item = self._result_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        QMessageBox.information(self, "知识库片段", _knowledge_hit_text(data))


def _announcement_detail_text(announcement: dict[str, object]) -> str:
    parts = [
        f"标题：{announcement.get('title') or '未命名通知'}",
        f"课程：{announcement.get('course') or '未知课程'}",
    ]
    posted = announcement.get("posted_at")
    if posted:
        parts.append(f"发布时间：{posted}")
    body = str(announcement.get("body") or "").strip()
    if body:
        parts.append("")
        parts.append(body)
    return "\n".join(parts)


def _lecture_time_text(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "时间待定"
    try:
        return datetime.fromisoformat(raw).strftime("%m-%d %H:%M")
    except ValueError:
        return raw


def _lecture_detail_text(lecture: dict[str, object]) -> str:
    fields = [
        ("时间", _lecture_time_text(lecture.get("time"))),
        ("地点", lecture.get("location") or "地点待定"),
        ("主讲人", lecture.get("speaker") or "主讲人待定"),
        ("链接", lecture.get("link") or ""),
    ]
    return "\n".join(f"{label}：{value}" for label, value in fields if value)


def _knowledge_hit_text(hit: dict[str, object]) -> str:
    metadata = hit.get("metadata")
    lines = [
        f"来源：{hit.get('source') or 'unknown'}",
        f"标识：{hit.get('identifier') or ''}",
        f"分数：{float(hit.get('score') or 0):.4f}",
    ]
    if isinstance(metadata, dict) and metadata:
        lines.append(f"元数据：{metadata}")
    lines.append("")
    lines.append(str(hit.get("text") or ""))
    return "\n".join(lines)


def _material_id(material: dict[str, object]) -> int | None:
    value = material.get("id")
    return value if isinstance(value, int) else None


def _plib_item_text(material: dict[str, object]) -> str:
    material_id = material.get("id", "?")
    title = str(material.get("title") or "未命名资料")
    course = str(material.get("course") or "未知课程")
    material_type = str(material.get("type") or "未知类型")
    stats = "下载 {downloads} · 浏览 {views}".format(
        downloads=material.get("downloads", 0),
        views=material.get("views", 0),
    )
    return f"#{material_id}  {title}\n{course} · {material_type} · {stats}"


def _plib_detail_text(material: dict[str, object]) -> str:
    fields = [
        ("编号", material.get("id")),
        ("标题", material.get("title")),
        ("课程", material.get("course")),
        ("院系", material.get("department")),
        ("类型", material.get("type")),
        ("学期", material.get("semester")),
        ("上传者", material.get("uploader")),
        ("上传时间", material.get("date") or material.get("upload_time")),
        ("下载次数", material.get("downloads")),
        ("浏览次数", material.get("views")),
        ("简介", material.get("description")),
        ("链接", material.get("url") or material.get("download_url")),
    ]
    lines = [f"{label}：{value}" for label, value in fields if value not in (None, "")]
    files = material.get("files")
    if isinstance(files, list) and files:
        lines.append("文件：")
        lines.extend(f"- {item}" for item in files[:8])
    return "\n".join(lines) if lines else "暂无详情"


def _plib_download_text(data: dict[str, object]) -> str:
    downloads = data.get("downloads")
    paths: list[str] = []
    if isinstance(downloads, list):
        for item in downloads:
            if isinstance(item, dict):
                path = item.get("path") or item.get("file") or item.get("saved_path")
                if path:
                    paths.append(str(path))
    quota = data.get("quota_remaining")
    lines = ["下载完成。"]
    if paths:
        lines.append("保存位置：")
        lines.extend(paths)
    if quota is not None:
        lines.append(f"今日剩余下载次数：{quota}")
    return "\n".join(lines)


def _treehole_detail_row(item: dict[str, object]) -> QFrame:
    row = ClickableFrame()
    row.setObjectName("TreeholeDetailRow")
    row.setToolTip("点击在 Safari 打开树洞")
    row.clicked.connect(lambda: _open_external_url(TREEHOLE_WEB_URL))

    pid = str(item.get("pid") or "?")
    delta = int(item.get("delta") or 0)
    header = QLabel(f"#{pid} · 新增 {delta} 条回复")
    header.setObjectName("TodoTitle")
    body = QLabel(str(item.get("text") or "暂无树洞正文摘要"))
    body.setObjectName("CardBody")
    body.setWordWrap(True)

    layout = QVBoxLayout(row)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(6)
    layout.addWidget(header)
    layout.addWidget(body)

    comments = item.get("new_comments")
    if isinstance(comments, list) and comments:
        for comment in comments:
            if isinstance(comment, dict):
                layout.addWidget(_comment_label(comment))
    else:
        hint = QLabel("本次只检测到回复数增长，未返回评论正文。")
        hint.setObjectName("TodoCourse")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    return row


def _dean_update_row(item: dict[str, object]) -> QFrame:
    url = str(item.get("url") or "").strip()
    row = ClickableFrame() if url else QFrame()
    row.setObjectName("TodoRow")
    if url and isinstance(row, ClickableFrame):
        row.setToolTip("点击在 Safari 打开对应教务内容")
        row.clicked.connect(lambda: _open_external_url(url))
    layout = QVBoxLayout(row)
    layout.setContentsMargins(8, 7, 8, 7)
    layout.setSpacing(3)

    title = QLabel(str(item.get("title") or "未命名教务内容"))
    title.setObjectName("TodoTitle")
    title.setWordWrap(True)
    meta_parts = [
        str(item.get("source_label") or "教务部"),
        str(item.get("date") or ""),
    ]
    meta = QLabel(" · ".join(part for part in meta_parts if part))
    meta.setObjectName("TodoCourse")
    meta.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(meta)
    return row


def _comment_label(comment: dict[str, object]) -> QLabel:
    who = str(comment.get("name_tag") or "洞友")
    time_text = _timestamp_text(comment.get("timestamp"))
    text = str(comment.get("text") or "")
    label = QLabel(f"{who} · {time_text}\n{text}".strip())
    label.setObjectName("TreeholeComment")
    label.setWordWrap(True)
    return label


def _timestamp_text(value: object) -> str:
    try:
        timestamp = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "时间未知"
    return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _calendar_candidates(assignments: list[dict[str, object]]) -> list[dict[str, object]]:
    """Future, deadline-bearing, incomplete assignments shaped for the calendar dialog.

    Drops completed / no-deadline / overdue items (an alarm in the past is
    useless), and sorts soonest-first. Each entry carries both the display
    `label` and the fields `CalendarReminderTool` needs.
    """
    now = datetime.now().astimezone()
    entries: list[tuple[datetime, dict[str, object]]] = []
    for item in assignments:
        if not isinstance(item, dict) or item.get("completed"):
            continue
        deadline = parse_datetime(item.get("deadline_iso"))
        if deadline is None or deadline < now:
            continue
        title = str(item.get("title") or "未命名作业")
        course = str(item.get("course_name") or item.get("course_title") or "")
        summary = f"{course}｜{title}" if course else title
        note_lines = [f"课程：{course}"] if course else []
        note_lines.append("由 PKU Captain 添加")
        notes = "\n".join(note_lines)
        entries.append(
            (
                deadline,
                {
                    "summary": summary,
                    "deadline_iso": str(item.get("deadline_iso")),
                    "notes": notes,
                    "label": f"{_deadline_text(item)} · {summary}",
                },
            )
        )
    entries.sort(key=lambda pair: pair[0])
    return [entry for _, entry in entries]


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
