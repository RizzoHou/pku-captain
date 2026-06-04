"""Execution coverage for the PR #4 dashboard dialogs as refactored to take an
injected tool and run blocking calls through `run_async`.

Two things are proven, both headless/offscreen and deterministic (a fake tool,
no network): (1) every dialog constructs with the new ``(tool, parent)``
signatures — catches signature/import regressions across all of them; (2) one
async dialog runs end-to-end through ``run_async`` and updates its widget —
since every async dialog shares the one helper, driving it once de-risks all.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import src.ui.dashboard as dashboard  # noqa: E402
from src.tools.base import Tool, ToolResult  # noqa: E402


class FakeTool(Tool):
    name = "fake"
    description = "fake"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, data: Any = None) -> None:
        self._data = data if data is not None else {}

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, data=self._data)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain() -> None:
    QThreadPool.globalInstance().waitForDone(3000)
    QApplication.processEvents()
    QApplication.processEvents()


def test_all_dialogs_construct_with_injected_tool(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Treehole auth is not a Tool; stub it so construction stays hermetic
    # (its __init__ kicks off an async status check).
    class FakeAuth:
        def status(self) -> dict[str, object]:
            return {"ok": False, "message": "尚未登录"}

    monkeypatch.setattr(dashboard, "TreeholeAuthService", FakeAuth)

    tool = FakeTool()
    # Constructors that take a tool — a signature/import error raises here.
    dashboard.PLibSearchDialog(tool)
    dashboard.PLibLoginDialog(tool)
    dashboard.AnnouncementDetailDialog(tool, "id-1")
    dashboard.LectureSearchDialog(tool)
    dashboard.RemindersDialog(tool)
    dashboard.MemoryDialog(tool)
    dashboard.KnowledgeSearchDialog(tool)
    dashboard.TreeholeMessagesDialog({"message": "x", "updates": []})

    # Notification dialog takes an injected service so it stays hermetic
    # (its real service would read the host's LaunchAgents on construct).
    class FakeNotifyService:
        def status(self) -> dict[str, object]:
            return {
                "supported": True,
                "binary_available": True,
                "logged_in": True,
                "enabled": False,
                "interval": 60,
                "message": "通知未开启",
            }

    dashboard.TreeholeNotificationDialog(service=FakeNotifyService())
    _drain()  # let any __init__-launched async calls settle


def test_plib_search_dialog_runs_async_end_to_end(app: QApplication) -> None:
    tool = FakeTool(
        {
            "results": [
                {"id": 7, "title": "高数试卷", "type": "试卷", "downloads": 9, "views": 3}
            ],
            "total": 1,
        }
    )
    dialog = dashboard.PLibSearchDialog(tool)
    dialog._query_input.setText("高数")
    dialog._search()  # _run_tool -> run_async -> _AsyncTask.run -> queued callback
    _drain()

    assert dialog._result_list.count() == 1
    assert dialog._results[0]["id"] == 7


class _ToggleNotifyService:
    """In-memory fake of TreeholeNotificationService for the dialog's UI logic."""

    def __init__(self) -> None:
        self._enabled = False
        self._interval = 600

    def status(self) -> dict[str, object]:
        return {
            "supported": True,
            "binary_available": True,
            "logged_in": True,
            "enabled": self._enabled,
            "interval": self._interval,
            "message": "通知已开启" if self._enabled else "通知未开启",
        }

    def enable(self, interval: int | None = None) -> dict[str, object]:
        self._enabled = True
        if interval is not None:
            self._interval = interval
        return {"ok": True, "interval": self._interval, "message": "已开启"}

    def disable(self) -> dict[str, object]:
        self._enabled = False
        return {"ok": True, "message": "已关闭"}


def test_notification_dialog_toggle_updates_buttons(app: QApplication) -> None:
    service = _ToggleNotifyService()
    dialog = dashboard.TreeholeNotificationDialog(service=service)

    # Disabled state: enable offered, disable inert.
    assert dialog._enable_button.text() == "开启通知"
    assert dialog._enable_button.isEnabled() is True
    assert dialog._disable_button.isEnabled() is False

    dialog._interval_combo.setCurrentIndex(1)  # 每 5 分钟 = 300
    dialog._enable()  # routes through run_async
    _drain()

    assert service._enabled is True
    assert service._interval == 300
    assert dialog._enable_button.text() == "更新设置"
    assert dialog._disable_button.isEnabled() is True

    dialog._disable()
    _drain()

    assert service._enabled is False
    assert dialog._enable_button.text() == "开启通知"
    assert dialog._disable_button.isEnabled() is False


def test_notification_dialog_disables_controls_when_unsupported(app: QApplication) -> None:
    class _Unsupported:
        def status(self) -> dict[str, object]:
            return {
                "supported": False,
                "binary_available": False,
                "logged_in": False,
                "enabled": False,
                "interval": 60,
                "message": "系统通知仅支持 macOS",
            }

    dialog = dashboard.TreeholeNotificationDialog(service=_Unsupported())
    assert dialog._enable_button.isEnabled() is False
    assert dialog._disable_button.isEnabled() is False
    assert dialog._interval_combo.isEnabled() is False
