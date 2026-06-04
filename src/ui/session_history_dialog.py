"""SessionHistoryDialog — pick a saved chat session to reopen or delete.

A modal list-picker following the dashboard-dialog convention (object names
from `styles.py`). Listing reads the local `SessionStore` (disk only, no
network), so no `run_async` is needed. The currently-open session is marked
and its 删除 button disabled, so a user can't delete the session that the
next auto-save would immediately recreate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ..core.session_store import SessionStore


class SessionHistoryDialog(QDialog):
    """List saved sessions; let the user open or delete one."""

    def __init__(
        self,
        store: SessionStore,
        *,
        current_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._current_id = current_id
        self.selected_id: str | None = None

        self.setWindowTitle("历史会话")
        self.resize(560, 560)

        title = QLabel("历史会话")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("选择一个会话打开；当前会话不可删除。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        self._list = QListWidget()
        self._list.setObjectName("PLibResultList")
        self._list.itemDoubleClicked.connect(lambda _item: self._open())
        self._list.currentItemChanged.connect(lambda *_: self._sync_buttons())

        self._open_button = QPushButton("打开")
        self._open_button.setObjectName("PrimaryButton")
        self._open_button.clicked.connect(self._open)
        self._delete_button = QPushButton("删除")
        self._delete_button.setObjectName("SecondaryButton")
        self._delete_button.clicked.connect(self._delete)
        close_button = QPushButton("关闭")
        close_button.setObjectName("SecondaryButton")
        close_button.clicked.connect(self.reject)

        actions = QHBoxLayout()
        actions.addWidget(self._open_button)
        actions.addWidget(self._delete_button)
        actions.addStretch()
        actions.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._list, 1)
        layout.addLayout(actions)

        self._reload()

    def _reload(self) -> None:
        self._list.clear()
        for meta in self._store.list_sessions():
            session_id = str(meta.get("id", ""))
            is_current = session_id == self._current_id
            title = str(meta.get("title", "未命名会话"))
            label = f"{title}{'（当前）' if is_current else ''}\n{_subtitle(meta)}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, session_id)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        item = self._list.currentItem()
        has_selection = item is not None
        self._open_button.setEnabled(has_selection)
        is_current = has_selection and item.data(Qt.ItemDataRole.UserRole) == self._current_id
        self._delete_button.setEnabled(has_selection and not is_current)

    def _open(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self.selected_id = str(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    def _delete(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        session_id = str(item.data(Qt.ItemDataRole.UserRole))
        if session_id == self._current_id:
            return
        self._store.delete(session_id)
        self._reload()


def _subtitle(meta: dict[str, object]) -> str:
    updated = str(meta.get("updated_at", "")).replace("T", " ")[:16]
    count = meta.get("message_count", 0)
    return f"{updated}  ·  {count} 条消息".strip()
