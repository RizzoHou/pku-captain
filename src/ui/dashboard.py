"""Dashboard entry surface for PKU Captain."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.credentials import CredentialStore
from ..tools.base import Tool, ToolRegistry
from ..tools.dean_updates import DeanInboxStore
from ..tools.treehole_updates import (
    DEFAULT_NOTIFY_INTERVAL,
    TreeholeAuthService,
    TreeholeHistoryStore,
    TreeholeInboxStore,
    TreeholeNotificationService,
)
from .formatters import (
    group_dean_by_category,
    parse_datetime,
    recent_announcements,
    split_dean_items,
    upcoming_assignments,
)
from .login_dialog import LoginDialog
from .tool_call_worker import run_async

# Dean sources whose items have fetchable full text (notice_show / rules_show);
# their rows open an in-app detail dialog, others (download/openinfo) open Safari.
_DEAN_DETAIL_SOURCES = {"notice", "rules_school", "rules_national"}

if TYPE_CHECKING:
    from ..core import MemoryLearnService
    from ..tools import DocBaseReader


TREEHOLE_WEB_URL = "https://treehole.pku.edu.cn/ch/web/"
PKU3B_WEB_URL = "https://course.pku.edu.cn/"


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
    auto_refresh_settings_requested = pyqtSignal()
    # Emitted after the treehole dialog closes so the window can reconfigure the
    # auto-sync timer (notification enable/disable/interval may have changed).
    treehole_settings_changed = pyqtSignal()

    def __init__(
        self,
        *,
        mode_label: str,
        tools: ToolRegistry | None = None,
        memory_learner: MemoryLearnService | None = None,
        doc_reader: DocBaseReader | None = None,
        treehole_inbox: TreeholeInboxStore | None = None,
        treehole_history: TreeholeHistoryStore | None = None,
        dean_inbox: DeanInboxStore | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("DashboardPanel")
        self._tools = tools
        self._memory_learner = memory_learner
        # Encapsulated vision reader for the 文档库 dialog's 让 Captain 阅读 button
        # (standalone text answer, decoupled from the chat brain). None offline /
        # without a Kimi key → the dialog is browse / open-PDF only.
        self._doc_reader = doc_reader
        # Accumulates unread treehole updates so a poll's result sticks on the
        # card instead of vanishing on the next empty poll. In-memory by default
        # (tests / no-disk); MainWindow injects a persisted store.
        self._treehole_inbox = treehole_inbox or TreeholeInboxStore()
        # Append-only log of every new reply ever surfaced, fed alongside the
        # inbox but never cleared on read — backs the dialog's 历史消息 tab.
        self._treehole_history = treehole_history or TreeholeHistoryStore()
        # Never-lossy accumulator of dean items; the card renders a recency
        # window and the dialog exposes the full 近期 + 历史 archive. In-memory
        # by default (tests / no-disk); MainWindow injects a persisted store.
        self._dean_inbox = dean_inbox or DeanInboxStore()

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
        self._auto_refresh_button = QPushButton("自动刷新")
        self._auto_refresh_button.setObjectName("SecondaryButton")
        self._auto_refresh_button.clicked.connect(self.auto_refresh_settings_requested)
        self._briefing_button = QPushButton("今日简报")
        self._briefing_button.setObjectName("PrimaryButton")
        self._briefing_button.clicked.connect(self.morning_briefing_requested)
        self._treehole_button = QPushButton("◉ 树洞")
        self._treehole_button.setObjectName("HeaderTreeholeButton")
        self._treehole_button.setToolTip("查看树洞新消息")
        self._treehole_button.clicked.connect(self._show_treehole_dialog)
        self._memory_button = QPushButton("记忆")
        self._memory_button.setObjectName("SecondaryButton")
        self._memory_button.clicked.connect(self._show_memory_dialog)
        self._knowledge_button = QPushButton("文档库")
        self._knowledge_button.setObjectName("SecondaryButton")
        self._knowledge_button.clicked.connect(self._show_docbase_dialog)
        # Single entry point to the universal 账号中心 (treehole / P-Lib / models).
        # Not gated on online mode — credentials (and model endpoints) are
        # configured here even offline, taking effect on the next launch.
        self._account_button = QPushButton("账号")
        self._account_button.setObjectName("SecondaryButton")
        self._account_button.setToolTip("登录北大统一身份、P-Lib，并配置对话模型")
        self._account_button.clicked.connect(lambda: self._open_account_dialog())

        header = QGridLayout()
        header.addWidget(title, 0, 0)
        header.addWidget(subtitle, 1, 0)
        header.addWidget(self._updated_label, 2, 0)
        header.addWidget(self._otp_input, 0, 1, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._refresh_button, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(
            self._auto_refresh_button, 0, 3, 2, 1, Qt.AlignmentFlag.AlignRight
        )
        header.addWidget(self._briefing_button, 0, 4, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._treehole_button, 0, 5, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._memory_button, 0, 6, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._knowledge_button, 0, 7, 2, 1, Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._account_button, 0, 8, 2, 1, Qt.AlignmentFlag.AlignRight)

        self._cards = {
            "schedule": ScheduleCard(),
            "pku3b_assignments": AssignmentTodoCard(),
            "treehole_updates": TreeholeMessagesCard(),
            "dean_updates": DeanUpdatesCard(),
            "plib_materials": PLibMaterialsCard(),
            "pku3b_announcements": AnnouncementsCard(),
        }
        treehole_card = self._cards["treehole_updates"]
        if isinstance(treehole_card, TreeholeMessagesCard):
            treehole_card.view_requested.connect(self._show_treehole_dialog)
            treehole_card.refresh_requested.connect(
                self._partial_refresh_emitter("treehole_updates")
            )
        dean_card = self._cards["dean_updates"]
        if isinstance(dean_card, DeanUpdatesCard):
            dean_card.view_requested.connect(self._show_dean_dialog)
            dean_card.detail_requested.connect(self._show_dean_detail)
            dean_card.refresh_requested.connect(self._partial_refresh_emitter("dean_updates"))
        plib_card = self._cards["plib_materials"]
        if isinstance(plib_card, PLibMaterialsCard):
            plib_card.login_requested.connect(lambda: self._open_account_dialog())
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
        self._knowledge_button.setEnabled("doc_search" in (self._tools or ()))
        if isinstance(assignment_card, AssignmentTodoCard):
            assignment_card.set_calendar_enabled("calendar_reminder" in (self._tools or ()))

        # Reflect unread carried over from a previous session before the first poll.
        if self._treehole_inbox.unread_count():
            self._render_treehole()
        # Paint dean items restored from the persisted inbox before the first poll.
        if self._dean_inbox.entries():
            self._render_dean()

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

    def set_announcement_history(self, items: list[dict[str, object]]) -> None:
        card = self._cards.get("pku3b_announcements")
        if isinstance(card, AnnouncementsCard):
            card.set_history(items)

    def announcement_history(self) -> list[dict[str, object]]:
        card = self._cards.get("pku3b_announcements")
        if isinstance(card, AnnouncementsCard):
            return card.history_items()
        return []

    def set_treehole_updates(self, data: dict[str, object]) -> None:
        """Merge a poll's updates into the unread inbox and re-render the card.

        Accumulates rather than replaces, so a reply surfaced by one poll stays
        visible until the user opens the dialog (mark-as-read) — the next empty
        poll no longer blanks it. The poll's own ``message`` is only used when
        the inbox is empty; otherwise the count drives the summary.
        """
        updates = data.get("updates")
        if isinstance(updates, list):
            poll = [u for u in updates if isinstance(u, dict)]
            # Feed both from the raw poll, before any mark-as-read clear: the
            # inbox drives the unread badge (cleared on open), the history is a
            # permanent time-ordered log (never cleared on open).
            self._treehole_inbox.merge(poll)
            self._treehole_history.merge(poll)
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
        """Merge a poll's snapshot into the inbox and re-render the windowed card.

        Accumulates rather than replaces (the tool's ``items`` is the full
        current snapshot), so a dean item stays cached and never vanishes on the
        next poll; the card shows only the recency window and the rest is reached
        via the 历史 section of the dialog.
        """
        items = data.get("items")
        if isinstance(items, list):
            self._dean_inbox.merge([i for i in items if isinstance(i, dict)])
        self._render_dean()

    def _render_dean(self, *, fallback_message: str = "", status: str = "ok") -> None:
        entries = self._dean_inbox.entries()
        recent, history = split_dean_items(entries)
        if status == "error":
            message = fallback_message or "教务部不可用"
        elif recent:
            message = f"近期教务部内容（{len(recent)} 条）"
        elif history:
            message = "近期暂无新内容，点击标题查看历史"
        else:
            message = fallback_message or "暂无教务部内容"
        card = self._cards.get("dean_updates")
        if isinstance(card, DeanUpdatesCard):
            card.set_updates(
                {"message": message, "updates": recent, "status": status}
            )

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
        if key == "dean_updates":
            # Keep accumulated dean items visible; only the summary shows the
            # error, so a transient poll failure does not wipe the card.
            self._render_dean(
                fallback_message=f"教务部不可用：{message}", status="error"
            )
            return
        if key in self._cards:
            self._cards[key].set_body(f"不可用：{message}", "error")

    def set_refresh_busy(self, busy: bool) -> None:
        self._refresh_button.setEnabled(not busy)
        self._refresh_button.setText("刷新中" if busy else "刷新")

    def set_auto_refresh_text(self, text: str) -> None:
        self._auto_refresh_button.setText(text)

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
        dialog = TreeholeMessagesDialog(
            self._treehole_data, self, history=self._treehole_history
        )
        # Login moved to the account center; opening it (nested) then re-checks
        # this dialog's status so a fresh login reflects without reopening.
        dialog.login_requested.connect(
            lambda: self._open_account_dialog(on_close=dialog._refresh_auth_status)
        )
        # Opening the list marks the accumulated unread as read: empty the inbox
        # (the dialog already captured a snapshot) so the card/badge reset.
        self._treehole_inbox.clear()
        self._render_treehole()
        dialog.exec()
        # The dialog nests the notification settings dialog; once it closes any
        # enable/disable/interval change is persisted, so reconfigure the timer.
        self.treehole_settings_changed.emit()

    def _show_dean_dialog(self) -> None:
        entries = self._dean_inbox.entries()
        recent, history = split_dean_items(entries)
        dialog = DeanMessagesDialog(recent, history, self)
        dialog.detail_requested.connect(self._show_dean_detail)
        dialog.exec()

    def _show_dean_detail(self, item: dict[str, object]) -> None:
        tool = self._require_tool("dean_resources", "教务详情")
        if tool is None:
            return
        DeanDetailDialog(tool, item, self).exec()

    def _show_plib_dialog(self) -> None:
        tool = self._require_tool("plib_materials", "P-Lib 资料搜索")
        if tool is None:
            return
        PLibSearchDialog(tool, self).exec()

    def _open_account_dialog(self, on_close: Callable[[], None] | None = None) -> None:
        """Open the universal 账号中心. Not gated on online mode — model endpoints
        and credentials are configured here even offline (they take effect on
        the next launch); only the live treehole SMS + P-Lib validation need the
        network, which the dialog handles via the injected auth service / tool.
        """
        offline = self._online_tool("treehole_updates") is None
        dialog = LoginDialog(
            store=CredentialStore(),
            auth=None if offline else TreeholeAuthService(),
            plib_tool=self._online_tool("plib_materials"),
            offline=offline,
            parent=self,
        )
        dialog.credentials_changed.connect(self._on_credentials_changed)
        dialog.exec()
        if on_close is not None:
            on_close()

    def _on_credentials_changed(self, keys: list[str]) -> None:
        """Refresh the cards whose backing credentials the account dialog
        updated (treehole / P-Lib / the pku3b cards a 统一身份 login provisions).
        Model changes carry no live card — the dialog already tells the user
        they take effect after a restart."""
        live = ("treehole_updates", "plib_materials", "pku3b_assignments", "pku3b_announcements")
        scoped = [key for key in keys if key in live]
        if scoped:
            self.partial_refresh_requested.emit(scoped)

    def _show_announcement_detail(self, announcement: dict[str, object] | str) -> None:
        tool = self._require_tool("pku3b_announcements", "课程通知详情")
        if tool is None:
            return
        AnnouncementDetailDialog(tool, announcement, self).exec()

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

    def _show_docbase_dialog(self) -> None:
        search_tool = self._online_tool("doc_search")
        if search_tool is None:
            QMessageBox.information(self, "文档库", "文档库不可用。")
            return
        # The standalone reader (encapsulated Kimi vision Q&A) powers
        # "让 Captain 阅读"; without a Kimi key it is None and the dialog is
        # browse / open-PDF only.
        DocBaseDialog(search_tool, self._doc_reader, self).exec()


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

    detail_requested = pyqtSignal(dict)
    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 4

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(220)
        self._items: list[dict[str, object]] = []
        self._history_items: list[dict[str, object]] = []
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
        self._history_button = QPushButton("历史通知")
        self._history_button.setObjectName("InlineToggleButton")
        self._history_button.clicked.connect(self._show_history)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        actions.addWidget(self._toggle_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(self._refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        actions.addWidget(self._history_button, 0, Qt.AlignmentFlag.AlignLeft)
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
        all_items = (
            [item for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else []
        )
        # 历史通知 keeps every announcement ever seen; the main card's 最近
        # section shows only those posted within the last month (by posted_date,
        # attached when the tool runs with resolve_dates). Merge the full list
        # into history first, then narrow what 最近 renders.
        self._merge_history(all_items)
        self._items = recent_announcements(all_items)
        total = data.get("total_reported") or len(all_items)
        self._summary_label.setText(f"最近 {len(self._items)} 条 / 总计 {total} 条")
        self._summary_label.setStyleSheet("")
        self._expanded = False
        self._render()

    def _render(self) -> None:
        self._clear_items()
        if not self._items:
            text = "近一个月暂无课程通知" if self._history_items else "暂无课程通知"
            empty = QLabel(text)
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
        button.setToolTip("点击查看课程通知详情")
        button.clicked.connect(
            lambda _checked=False, payload=dict(item): self.detail_requested.emit(payload)
        )
        return button

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._render()

    def _show_history(self) -> None:
        dialog = AnnouncementsHistoryDialog(self._history_items, self)
        dialog.detail_requested.connect(self.detail_requested.emit)
        dialog.exec()

    def set_history(self, items: list[dict[str, object]]) -> None:
        self._history_items = [dict(item) for item in items if isinstance(item, dict)]

    def history_items(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._history_items]

    def _merge_history(self, items: list[dict[str, object]]) -> None:
        merged = {_announcement_identity(item): dict(item) for item in self._history_items}
        for item in items:
            merged[_announcement_identity(item)] = dict(item)
        self._history_items = list(merged.values())

    def _clear_items(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


class AnnouncementsHistoryDialog(QDialog):
    """Historical course notices accumulated from dashboard refreshes."""

    detail_requested = pyqtSignal(dict)

    def __init__(
        self,
        items: list[dict[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史通知")
        self.resize(700, 560)

        title = QLabel("历史通知")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(f"已记录 {len(items)} 条课程通知")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        host = QWidget()
        list_layout = QVBoxLayout(host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        if items:
            for item in items:
                list_layout.addWidget(self._announcement_history_row(item))
        else:
            empty = QLabel("暂无历史通知")
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            list_layout.addWidget(empty)
        list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("TreeholeMessageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)

        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()
        actions.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(scroll, 1)
        layout.addLayout(actions)

    def _announcement_history_row(self, item: dict[str, object]) -> QPushButton:
        course = str(item.get("course") or "未知课程")
        title = str(item.get("title") or "未命名通知")
        button = QPushButton(f"{course}\n{title}")
        button.setObjectName("ListRowButton")
        button.setToolTip("点击查看课程通知详情")
        button.clicked.connect(
            lambda _checked=False, payload=dict(item): self.detail_requested.emit(payload)
        )
        return button


def _announcement_identity(item: dict[str, object]) -> str:
    raw = "|".join(str(item.get(key) or "") for key in ("id", "course", "title"))
    return raw.casefold()


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
    """Dashboard card for recent Dean's Office public resources.

    Shows a recency window of accumulated items; the clickable title opens the
    full 近期 + 历史 archive dialog. Notice / rule rows open an in-app detail
    dialog (``detail_requested``); file rows open Safari directly.
    """

    view_requested = pyqtSignal()
    detail_requested = pyqtSignal(dict)
    refresh_requested = pyqtSignal()
    _COLLAPSED_LIMIT = 4

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DashboardCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(196)

        # Clickable title opens the 近期 / 历史 dialog (user-chosen entry point).
        title_frame = ClickableFrame()
        title_frame.setToolTip("点击查看全部教务消息（近期 / 历史）")
        title_frame.clicked.connect(self.view_requested)
        title_label = QLabel("教务更新 ▸")
        title_label.setObjectName("CardTitle")
        title_row = QHBoxLayout(title_frame)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        title_row.addStretch()

        self._summary_label = QLabel("教务部近期内容")
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
        layout.addWidget(title_frame)
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
        message = str(data.get("message") or "暂无教务部内容")
        status = str(data.get("status") or "ok")
        updates = data.get("updates")
        self._summary_label.setText(message)
        self._summary_label.setStyleSheet(
            "color: #b42318;" if status == "error" else ""
        )
        self._clear_items()
        # Empty state is a single line (the summary above); no duplicate label.
        if not isinstance(updates, list) or not updates:
            return
        for item in updates[: self._COLLAPSED_LIMIT]:
            if isinstance(item, dict):
                self._list_layout.addWidget(
                    _dean_update_row(item, on_detail=self.detail_requested.emit)
                )
        hidden = len(updates) - self._COLLAPSED_LIMIT
        if hidden > 0:
            more = QLabel(f"还有 {hidden} 条，点击标题查看全部")
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
        hint_label = QLabel("点击课程块查看完整信息")
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
            block = CourseBlockWidget(title=title, detail=detail, note=note)
            block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tooltip_note = f"备注：{note}" if note else ""
            block.setToolTip(
                "\n".join(part for part in (title, detail, tooltip_note) if part)
            )
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
        lines = [
            f"课程：{course.get('title', '未命名课程')}",
            f"时间：{course.get('day_name', '')} {slot}",
            str(course.get("detail") or "暂无详细信息"),
            f"备注：{course.get('note') or '暂无官方备注'}",
        ]
        QMessageBox.information(self, "课程详情", "\n".join(lines))

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
    """Clickable course cell showing the full course info inline: title, the
    class details (上课信息 / 教师 / 考试信息), and a smaller official note."""

    clicked = pyqtSignal()

    def __init__(self, *, title: str, detail: str = "", note: str = "") -> None:
        super().__init__()
        self.setObjectName("CourseBlock")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        title_label = QLabel(title)
        title_label.setObjectName("CourseBlockTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)

        self._detail_label = QLabel(detail)
        self._detail_label.setObjectName("CourseBlockDetail")
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_label.setWordWrap(True)
        self._detail_label.setVisible(bool(detail))

        self._note_label = QLabel(note)
        self._note_label.setObjectName("CourseBlockNote")
        self._note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._note_label.setWordWrap(True)
        self._note_label.setVisible(bool(note))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addStretch()
        layout.addWidget(title_label)
        layout.addWidget(self._detail_label)
        layout.addWidget(self._note_label)
        layout.addStretch()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001,N802 - Qt callback.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _todo_row(item: dict[str, object]) -> QFrame:
    row = ClickableFrame()
    row.setObjectName("TodoRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.setToolTip("点击在 Safari 打开作业提交页")
    row.clicked.connect(lambda: _open_external_url(_pku3b_item_url(item)))

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


def _pku3b_item_url(item: dict[str, object], *, prefer_submit: bool = True) -> str:
    keys = ("submit_url", "url") if prefer_submit else ("url", "submit_url")
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return PKU3B_WEB_URL


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
    """Modal list of treehole updates opened from the header/card.

    Login itself now lives in the universal 账号中心 (`LoginDialog`); this dialog
    only shows the current treehole login status and a button that opens it
    (emitting `login_requested`).
    """

    login_requested = pyqtSignal()

    # Cap the history tab so a semester of records can't spawn thousands of
    # widgets in one scroll area; the store keeps everything, the view shows the
    # most recent slice.
    _HISTORY_DISPLAY_CAP = 200

    def __init__(
        self,
        data: dict[str, object],
        parent: QWidget | None = None,
        *,
        history: TreeholeHistoryStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("树洞新消息")
        self.resize(700, 680)
        self._auth = TreeholeAuthService()
        self._history = history
        self._pending: object = None

        title = QLabel("树洞新消息")
        title.setObjectName("DialogTitle")
        message = QLabel(str(data.get("message") or "暂无树洞新回复"))
        message.setObjectName("DialogSubtitle")
        message.setWordWrap(True)

        tabs = QTabWidget()
        tabs.setObjectName("TreeholeMessageTabs")
        tabs.addTab(self._build_new_tab(data), "新消息")
        tabs.addTab(self._build_history_tab(), "历史消息")

        auth_panel = self._build_auth_panel()

        notify_button = QPushButton("消息通知")
        notify_button.setObjectName("SecondaryButton")
        notify_button.setToolTip("设置 macOS 后台消息通知与检查间隔")
        notify_button.clicked.connect(self._open_notification_settings)
        self._clear_history_button = QPushButton("清空历史")
        self._clear_history_button.setObjectName("SecondaryButton")
        self._clear_history_button.setToolTip("清空全部历史消息记录")
        self._clear_history_button.clicked.connect(self._clear_history)
        self._clear_history_button.setEnabled(bool(history and history.count()))
        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(10)
        button_row.addWidget(notify_button, 0, Qt.AlignmentFlag.AlignLeft)
        button_row.addWidget(self._clear_history_button, 0, Qt.AlignmentFlag.AlignLeft)
        button_row.addStretch()
        button_row.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addWidget(auth_panel)
        layout.addWidget(tabs, 1)
        layout.addLayout(button_row)

        self._refresh_auth_status()

    def _build_new_tab(self, data: dict[str, object]) -> QScrollArea:
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
        return scroll

    def _build_history_tab(self) -> QScrollArea:
        host = QWidget()
        self._history_layout = QVBoxLayout(host)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._history_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setObjectName("TreeholeHistoryScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        scroll.setMinimumHeight(160)

        self._render_history()
        return scroll

    def _render_history(self) -> None:
        layout = self._history_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        records = self._history.entries() if self._history is not None else []
        if not records:
            empty = QLabel("暂无历史消息")
            empty.setObjectName("CardBody")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            layout.addStretch()
            return

        for record in records[: self._HISTORY_DISPLAY_CAP]:
            layout.addWidget(_treehole_history_row(record))
        hidden = len(records) - self._HISTORY_DISPLAY_CAP
        if hidden > 0:
            more = QLabel(f"仅显示最近 {self._HISTORY_DISPLAY_CAP} 条，另有 {hidden} 条更早记录。")
            more.setObjectName("TodoCourse")
            more.setWordWrap(True)
            layout.addWidget(more)
        layout.addStretch()

    def _clear_history(self) -> None:
        if self._history is None or not self._history.count():
            return
        confirm = QMessageBox.question(
            self,
            "清空历史消息",
            "确定清空全部历史消息记录吗？此操作不可恢复。",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._history.clear()
        self._render_history()
        self._clear_history_button.setEnabled(False)

    def _open_notification_settings(self) -> None:
        TreeholeNotificationDialog(parent=self).exec()

    def _build_auth_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("TreeholeAuthPanel")

        title = QLabel("树洞账户")
        title.setObjectName("TreeholeAuthTitle")
        self._auth_status = QLabel("正在检查登录状态...")
        self._auth_status.setObjectName("TreeholeAuthStatus")
        self._auth_status.setWordWrap(True)

        login_button = QPushButton("登录 / 管理")
        login_button.setObjectName("SecondaryButton")
        login_button.setToolTip("在账号中心登录北大统一身份并完成短信验证")
        login_button.clicked.connect(self.login_requested)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(2)
        text_block.addWidget(title)
        text_block.addWidget(self._auth_status)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addLayout(text_block, 1)
        header.addWidget(login_button, 0, Qt.AlignmentFlag.AlignVCenter)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(header)
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


class AnnouncementDetailDialog(QDialog):
    """Fetch and display one course announcement."""

    def __init__(
        self,
        tool: Tool,
        announcement: dict[str, object] | str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("课程通知详情")
        self.resize(720, 620)
        self._tool = tool
        self._pending: object = None
        self._item = dict(announcement) if isinstance(announcement, dict) else {}
        announcement_id = (
            str(self._item.get("id") or "").strip()
            if self._item
            else str(announcement).strip()
        )
        self._link = str(self._item.get("url") or "").strip()

        title = QLabel("课程通知详情")
        title.setObjectName("DialogTitle")
        self._subtitle = QLabel(
            f"公告 ID：{announcement_id}" if announcement_id else "公告 ID：未知"
        )
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
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch()
        if self._link:
            open_button = QPushButton("在 Safari 打开教学网")
            open_button.setObjectName("SecondaryButton")
            open_button.clicked.connect(self._open_external_page)
            actions.addWidget(open_button, 0, Qt.AlignmentFlag.AlignRight)
        actions.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addWidget(scroll, 1)
        layout.addLayout(actions)
        if announcement_id:
            self._load_detail(announcement_id)
        else:
            self._show_item_fallback()

    def _open_external_page(self) -> None:
        if self._link:
            _open_external_url(self._link)

    def _show_item_fallback(self) -> None:
        """Render the list item's own fields when no announcement id is known."""
        if not self._item:
            self._body_label.setText("无法加载公告详情：缺少公告 ID。")
            return
        self._subtitle.setText(
            "{course} · {posted}".format(
                course=self._item.get("course") or "未知课程",
                posted=self._item.get("posted_at") or "发布时间未知",
            )
        )
        self._body_label.setText(_announcement_detail_text(self._item))

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


class AutoRefreshSettingsDialog(QDialog):
    """Configure in-app dashboard auto-refresh and macOS notifications."""

    _INTERVAL_PRESETS = [
        ("每 1 分钟", 60),
        ("每 5 分钟", 300),
        ("每 10 分钟", 600),
        ("每 30 分钟", 1800),
        ("每 1 小时", 3600),
        ("自定义", 0),
    ]

    def __init__(
        self,
        *,
        enabled: bool,
        interval_seconds: int,
        notify_enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("自动刷新")
        self.resize(520, 320)

        title = QLabel("自动刷新")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("后台定时刷新 dashboard，发现新变化后由 Captain 整理并推送通知。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._enabled_checkbox = QCheckBox("启用自动刷新")
        self._enabled_checkbox.setChecked(enabled)
        self._notify_checkbox = QCheckBox("发现变化时发送 macOS 通知")
        self._notify_checkbox.setChecked(notify_enabled)

        interval_label = QLabel("刷新间隔")
        interval_label.setObjectName("TreeholeAuthStep")
        self._interval_combo = QComboBox()
        for text, value in self._INTERVAL_PRESETS:
            self._interval_combo.addItem(text, value)
        self._custom_minutes = QSpinBox()
        self._custom_minutes.setRange(1, 24 * 60)
        self._custom_minutes.setSuffix(" 分钟")
        self._custom_minutes.setValue(max(1, int(interval_seconds / 60)))

        preset_index = self._interval_combo.findData(interval_seconds)
        if preset_index < 0:
            preset_index = self._interval_combo.findData(0)
        self._interval_combo.setCurrentIndex(preset_index)
        self._interval_combo.currentIndexChanged.connect(self._sync_custom_enabled)
        self._sync_custom_enabled()

        note = QLabel(
            "第一次自动刷新只建立对比基线，不会推送历史消息。之后只有真实新增或变化的信息才会通知。"
        )
        note.setObjectName("CardBody")
        note.setWordWrap(True)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(10)
        controls.addWidget(interval_label)
        controls.addWidget(self._interval_combo, 1)
        controls.addWidget(self._custom_minutes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._enabled_checkbox)
        layout.addWidget(self._notify_checkbox)
        layout.addLayout(controls)
        layout.addWidget(note)
        layout.addStretch()
        layout.addWidget(buttons)

    def settings(self) -> dict[str, object]:
        return {
            "enabled": self._enabled_checkbox.isChecked(),
            "interval_seconds": self.interval_seconds(),
            "notify_enabled": self._notify_checkbox.isChecked(),
        }

    def interval_seconds(self) -> int:
        value = int(self._interval_combo.currentData())
        if value > 0:
            return value
        return int(self._custom_minutes.value()) * 60

    def _sync_custom_enabled(self) -> None:
        self._custom_minutes.setEnabled(int(self._interval_combo.currentData()) == 0)


class DeanMessagesDialog(QDialog):
    """Modal dean archive: 新消息 / 历史消息 tabs, each split into category columns.

    The two tabs separate recent from history; inside each tab every dean source
    (通知公告 / 校级规章 / 上级文件 / 资料下载 / 信息公开) gets its own column with
    an independent scroll, so the categories are browsable side by side instead of
    a single flat list. Notice / rule rows still open the in-app detail dialog.
    """

    detail_requested = pyqtSignal(dict)

    def __init__(
        self,
        recent: list[dict[str, object]],
        history: list[dict[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("教务部消息")
        self.resize(980, 680)
        # Floor at the 5-column footprint (5 × 168 + gaps/margins) so dragging the
        # dialog narrower can't clip the rightmost category out of reach (the
        # per-column scroll is vertical-only, with no horizontal scroll).
        self.setMinimumWidth(900)

        title = QLabel("教务部消息")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(f"新消息 {len(recent)} 条 · 历史 {len(history)} 条")
        subtitle.setObjectName("DialogSubtitle")

        self._tabs = QTabWidget()
        self._tabs.setObjectName("DeanMessageTabs")
        self._tabs.addTab(self._build_tab(recent), f"新消息 ({len(recent)})")
        self._tabs.addTab(self._build_tab(history), f"历史消息 ({len(history)})")

        close_button = QPushButton("关闭")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

    def _build_tab(self, items: list[dict[str, object]]) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(2, 6, 2, 2)
        row.setSpacing(8)
        for _source, label, col_items in group_dean_by_category(items):
            row.addWidget(self._build_column(label, col_items), 1)
        return host

    def _build_column(
        self, label: str, items: list[dict[str, object]]
    ) -> QFrame:
        column = QFrame()
        column.setObjectName("DeanColumn")
        outer = QVBoxLayout(column)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header = QLabel(f"{label} · {len(items)}")
        header.setObjectName("DeanColumnHeader")
        outer.addWidget(header)

        list_host = QWidget()
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)
        if items:
            for item in items:
                if isinstance(item, dict):
                    list_layout.addWidget(
                        _dean_update_row(
                            item,
                            on_detail=self.detail_requested.emit,
                            show_category=False,
                        )
                    )
        else:
            empty = QLabel("（暂无）")
            empty.setObjectName("CardBody")
            list_layout.addWidget(empty)
        list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("DeanColumnScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(list_host)
        outer.addWidget(scroll, 1)

        column.setMinimumWidth(168)
        return column


class DeanDetailDialog(QDialog):
    """Fetch and display one dean notice / rule, with an open-in-Safari fallback."""

    _ACTION_BY_SOURCE = {
        "notice": "notice_show",
        "rules_school": "rules_show",
        "rules_national": "rules_show",
    }

    def __init__(
        self, tool: Tool, item: dict[str, object], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("教务详情")
        self.resize(720, 620)
        self._tool = tool
        self._url = str(item.get("url") or "").strip()
        self._pending: object = None

        title = QLabel(str(item.get("title") or "教务详情"))
        title.setObjectName("DialogTitle")
        meta_parts = [
            str(item.get("source_label") or "教务部"),
            str(item.get("date") or ""),
        ]
        self._subtitle = QLabel(" · ".join(p for p in meta_parts if p))
        self._subtitle.setObjectName("DialogSubtitle")
        self._subtitle.setWordWrap(True)

        self._body_label = QLabel("正在加载教务详情...")
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
        body_host = QWidget()
        body_layout = QVBoxLayout(body_host)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.addWidget(self._body_label)
        body_layout.addStretch()
        scroll.setWidget(body_host)

        open_button = QPushButton("在 Safari 打开")
        open_button.setObjectName("SecondaryButton")
        open_button.setEnabled(bool(self._url))
        open_button.clicked.connect(self._open_in_safari)
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
        layout.addWidget(self._subtitle)
        layout.addWidget(scroll, 1)
        layout.addLayout(actions)

        self._load_detail(item)

    def _load_detail(self, item: dict[str, object]) -> None:
        action = self._ACTION_BY_SOURCE.get(str(item.get("source") or ""))
        try:
            resource_id = int(str(item.get("item_id") or ""))
        except ValueError:
            resource_id = 0
        if action is None or resource_id <= 0:
            self._body_label.setText("该条目不支持查看全文，可点击“在 Safari 打开”。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending = run_async(
            lambda: self._tool.invoke({"action": action, "id": resource_id}),
            on_done=self._on_detail_loaded,
            on_error=self._on_detail_error,
        )

    def _on_detail_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._body_label.setStyleSheet("color: #b42318;")
        self._body_label.setText(f"教务详情加载失败：{message}")

    def _on_detail_loaded(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        if not getattr(result, "success", False):
            self._body_label.setStyleSheet("color: #b42318;")
            self._body_label.setText(
                str(getattr(result, "error", "") or "教务详情加载失败")
            )
            return
        data = result.data if isinstance(result.data, dict) else {}
        text = str(data.get("text") or data.get("body") or data.get("content") or "").strip()
        date = str(data.get("date") or "").strip()
        if date and date not in self._subtitle.text():
            self._subtitle.setText(f"{self._subtitle.text()} · {date}".strip(" ·"))
        self._body_label.setText(text or "（无正文内容）")

    def _open_in_safari(self) -> None:
        if self._url:
            _open_external_url(self._url)


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


class DocBaseDialog(QDialog):
    """Browse the doc base and read documents with Captain (vision LLM).

    Replaces the embedding `KnowledgeSearchDialog`. The tree is built from the
    `doc_search` tool's browse payload (volume → 学部/院系 breadcrumb → 文档);
    the filter box re-runs `doc_search`. Double-click or 打开 PDF opens the real
    PDF in the OS viewer; 让 Captain 阅读 runs the encapsulated `DocBaseReader`
    (Kimi vision Q&A) when available and shows the distilled answer.
    """

    def __init__(
        self,
        search_tool: Tool,
        reader: DocBaseReader | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("文档库")
        self.resize(900, 720)
        self._search_tool = search_tool
        self._reader = reader
        self._docs: list[dict[str, object]] = []
        self._pending: object = None

        title = QLabel("文档库")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "浏览北大本科培养方案 / 选课手册 / 辅修双专业文档；"
            "双击打开 PDF，或让 Captain 阅读并回答其中的表格内容。"
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("输入关键词筛选（学院 / 专业 / 文档名）")
        self._filter_input.textChanged.connect(self._apply_filter)

        self._tree = QTreeWidget()
        self._tree.setObjectName("DocBaseTree")
        self._tree.setHeaderLabels(["文档", "页数"])
        self._tree.setColumnWidth(0, 580)
        self._tree.itemDoubleClicked.connect(lambda _item, _col: self._open_pdf())
        self._tree.currentItemChanged.connect(lambda *_: self._sync_buttons())

        self._status_label = QLabel("")
        self._status_label.setObjectName("CardBody")
        self._status_label.setWordWrap(True)

        self._open_button = QPushButton("打开 PDF")
        self._open_button.setObjectName("SecondaryButton")
        self._open_button.clicked.connect(self._open_pdf)
        self._read_button = QPushButton("让 Captain 阅读")
        self._read_button.setObjectName("PrimaryButton")
        self._read_button.clicked.connect(self._read_doc)
        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self._open_button)
        actions.addWidget(self._read_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._filter_input)
        layout.addWidget(self._tree, 1)
        layout.addWidget(self._status_label)
        layout.addLayout(actions)

        self._load_all()

    def _load_all(self) -> None:
        result = self._search_tool.invoke({})  # empty query → browse all
        data = result.data if getattr(result, "success", False) else []
        self._docs = [doc for doc in data if isinstance(doc, dict)]
        self._build_tree(self._docs)
        self._status_label.setText(f"共 {len(self._docs)} 篇文档")

    def _apply_filter(self, text: str) -> None:
        query = text.strip()
        if not query:
            self._build_tree(self._docs)
            self._status_label.setText(f"共 {len(self._docs)} 篇文档")
            return
        result = self._search_tool.invoke({"query": query, "top_k": 50})
        data = result.data if getattr(result, "success", False) else []
        docs = [doc for doc in data if isinstance(doc, dict)]
        self._build_tree(docs)
        self._status_label.setText(f"匹配 {len(docs)} 篇文档")

    def _build_tree(self, docs: list[dict[str, object]]) -> None:
        self._tree.clear()
        groups: dict[tuple[str, ...], QTreeWidgetItem] = {}

        def group_for(parts: tuple[str, ...]) -> QTreeWidgetItem | None:
            node: QTreeWidgetItem | None = None
            key: tuple[str, ...] = ()
            for part in parts:
                key = (*key, part)
                if key not in groups:
                    item = QTreeWidgetItem([part, ""])
                    if node is None:
                        self._tree.addTopLevelItem(item)
                    else:
                        node.addChild(item)
                    groups[key] = item
                node = groups[key]
            return node

        for doc in docs:
            crumb = [str(p) for p in (doc.get("breadcrumb") or [])]
            parts = tuple([str(doc.get("volume") or "")] + crumb)
            parent = group_for(parts)
            leaf = QTreeWidgetItem(
                [str(doc.get("title") or "未命名"), str(doc.get("pages") or "")]
            )
            leaf.setData(0, Qt.ItemDataRole.UserRole, doc)
            if parent is None:
                self._tree.addTopLevelItem(leaf)
            else:
                parent.addChild(leaf)
        self._tree.expandToDepth(0)
        self._sync_buttons()

    def _selected_doc(self) -> dict[str, object] | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _sync_buttons(self) -> None:
        doc = self._selected_doc()
        self._open_button.setEnabled(doc is not None)
        self._read_button.setEnabled(doc is not None and self._reader is not None)
        if self._reader is None:
            self._read_button.setToolTip("需要在线模式 + Kimi 视觉模型")

    def _open_pdf(self) -> None:
        doc = self._selected_doc()
        if doc is None:
            return
        path = str(doc.get("abs_path") or "")
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "文档库", "未找到该 PDF 文件。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _read_doc(self) -> None:
        doc = self._selected_doc()
        if doc is None or self._reader is None:
            return
        question, ok = QInputDialog.getText(
            self,
            "让 Captain 阅读",
            f"想了解《{doc.get('title') or '该文档'}》的什么？（留空则给出整体摘要）",
        )
        if not ok:
            return
        reader = self._reader
        path = str(doc.get("path") or "")
        focus = question.strip() or None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._status_label.setStyleSheet("")
        self._status_label.setText("Captain 正在阅读文档...")
        self._pending = run_async(
            lambda: reader.read(path, question=focus),
            on_done=self._on_read_done,
            on_error=self._on_read_error,
        )

    def _on_read_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._status_label.setStyleSheet("color: #b42318;")
        self._status_label.setText(f"阅读失败：{message}")

    def _on_read_done(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._status_label.setStyleSheet("")
        self._status_label.setText(f"共 {len(self._docs)} 篇文档")
        if not getattr(result, "success", False):
            QMessageBox.warning(
                self, "文档库", str(getattr(result, "error", "") or "阅读失败")
            )
            return
        data = result.data if isinstance(result.data, dict) else {}
        DocReadResultDialog(data, self).exec()


class DocReadResultDialog(QDialog):
    """Shows a doc_read answer (vision-distilled) in a read-only panel."""

    def __init__(self, data: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Captain 阅读结果")
        self.resize(720, 560)

        title = QLabel(str(data.get("title") or "阅读结果"))
        title.setObjectName("DialogTitle")
        pages = data.get("pages_read") or []
        meta_bits = [str(data.get("volume") or "")]
        if isinstance(pages, list) and pages:
            meta_bits.append(f"第 {pages[0]}–{pages[-1]} 页 / 共 {data.get('total_pages')} 页")
        subtitle = QLabel(" · ".join(bit for bit in meta_bits if bit))
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        answer = str(data.get("answer") or "")
        note = str(data.get("note") or "")
        body.setPlainText(f"{answer}\n\n{note}".strip())

        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(body, 1)
        layout.addLayout(actions)


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


def _treehole_history_row(record: dict[str, object]) -> QFrame:
    """One historical reply: which hole, who, when, and the comment text.

    History is flattened across holes (newest-first), so unlike the per-hole
    detail row each row must carry its own ``#pid``.
    """
    row = ClickableFrame()
    row.setObjectName("TreeholeDetailRow")
    row.setToolTip("点击在 Safari 打开树洞")
    row.clicked.connect(lambda: _open_external_url(TREEHOLE_WEB_URL))

    pid = str(record.get("pid") or "?")
    who = str(record.get("name_tag") or "洞友")
    time_text = _timestamp_text(record.get("timestamp"))
    header = QLabel(f"#{pid} · {who} · {time_text}")
    header.setObjectName("TodoTitle")
    body = QLabel(str(record.get("text") or "（无正文）"))
    body.setObjectName("CardBody")
    body.setWordWrap(True)

    layout = QVBoxLayout(row)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)
    layout.addWidget(header)
    layout.addWidget(body)

    hole_text = str(record.get("hole_text") or "").strip()
    if hole_text:
        context = QLabel(_clip(hole_text, 72))
        context.setObjectName("TodoCourse")
        context.setWordWrap(True)
        layout.addWidget(context)
    return row


def _dean_update_row(
    item: dict[str, object],
    on_detail: Callable[[dict[str, object]], None] | None = None,
    *,
    show_category: bool = True,
) -> QFrame:
    url = str(item.get("url") or "").strip()
    source = str(item.get("source") or "")
    item_id = str(item.get("item_id") or "").strip()
    # Notice / rule rows fetch full text in-app; file rows open Safari.
    wants_detail = (
        on_detail is not None and source in _DEAN_DETAIL_SOURCES and bool(item_id)
    )
    clickable = wants_detail or bool(url)
    row = ClickableFrame() if clickable else QFrame()
    row.setObjectName("TodoRow")
    if clickable and isinstance(row, ClickableFrame):
        if wants_detail:
            row.setToolTip("点击查看全文")
            row.clicked.connect(lambda it=dict(item): on_detail(it))
        else:
            row.setToolTip("点击在 Safari 打开对应教务内容")
            row.clicked.connect(lambda u=url: _open_external_url(u))
    layout = QVBoxLayout(row)
    layout.setContentsMargins(8, 7, 8, 7)
    layout.setSpacing(3)

    title = QLabel(str(item.get("title") or "未命名教务内容"))
    title.setObjectName("TodoTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    # The meta line carries a colored category pill (so the flat card list stays
    # browsable by tag) plus the date. Inside the dialog's category columns the
    # column header already names the category, so the pill is dropped there.
    date_text = str(item.get("date") or "").strip()
    meta_row = QHBoxLayout()
    meta_row.setContentsMargins(0, 0, 0, 0)
    meta_row.setSpacing(6)
    has_meta = False
    if show_category:
        pill = QLabel(str(item.get("source_label") or "教务部"))
        pill.setObjectName("DeanTagPill")
        pill.setProperty("deanSource", source or "other")
        meta_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignLeft)
        has_meta = True
    if date_text:
        date_label = QLabel(date_text)
        date_label.setObjectName("TodoCourse")
        meta_row.addWidget(date_label, 0, Qt.AlignmentFlag.AlignLeft)
        has_meta = True
    if has_meta:
        meta_row.addStretch()
        layout.addLayout(meta_row)
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
