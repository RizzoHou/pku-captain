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
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

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
    dashboard.CalendarReminderDialog(tool, [])
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


def test_dashboard_title_preserves_only_product_name(app: QApplication) -> None:
    panel = dashboard.DashboardPanel(mode_label="离线模式")
    titles = panel.findChildren(QLabel, "DashboardTitle")

    assert [title.text() for title in titles] == ["PKU Captain"]


def test_schedule_card_displays_official_note_smaller(app: QApplication) -> None:
    card = dashboard.ScheduleCard()
    card.set_schedule(
        {
            "blocks": [
                {
                    "day_key": "mon",
                    "day_name": "周一",
                    "start_slot": 1,
                    "end_slot": 2,
                    "title": "程序设计实习",
                    "detail": "理教407 | 教师：杨帅",
                    "note": "与软件设计实践互斥",
                }
            ]
        }
    )

    note_labels = card.findChildren(QLabel, "CourseBlockNote")
    assert [label.text() for label in note_labels] == ["与软件设计实践互斥"]


def test_dean_updates_card_renders_new_items(app: QApplication) -> None:
    card = dashboard.DeanUpdatesCard()
    card.set_updates(
        {
            "message": "教务部有 1 条新内容",
            "updates": [
                {
                    "title": "本科生学籍管理办法",
                    "source_label": "校级规章",
                    "date": "2026-06-05",
                }
            ],
        }
    )

    titles = card.findChildren(QLabel, "TodoTitle")
    assert [label.text() for label in titles] == ["本科生学籍管理办法"]


def test_calendar_candidates_filters_and_sorts(app: QApplication) -> None:
    candidates = dashboard._calendar_candidates(
        [
            {"title": "晚", "course_name": "C", "deadline_iso": "2099-02-01T10:00:00"},
            {"title": "早", "course_name": "C", "deadline_iso": "2099-01-01T10:00:00"},
            {
                "title": "完成",
                "course_name": "C",
                "deadline_iso": "2099-01-01T10:00:00",
                "completed": True,
            },
            {"title": "无期限", "course_name": "C", "deadline_iso": None},
            {"title": "过期", "course_name": "C", "deadline_iso": "2000-01-01T10:00:00"},
        ]
    )
    # Only future + incomplete + deadline-bearing survive, soonest first.
    assert [c["summary"] for c in candidates] == ["C｜早", "C｜晚"]
    assert candidates[0]["deadline_iso"] == "2099-01-01T10:00:00"
    assert "由 PKU Captain 添加" in candidates[0]["notes"]


def test_calendar_dialog_adds_selected_and_marks_rows(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The modal info/warning boxes would block a headless run — stub them.
    monkeypatch.setattr(dashboard.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(dashboard.QMessageBox, "warning", lambda *a, **k: None)

    summary = "测试课｜作业X"
    tool = FakeTool(
        {
            "calendar": "PKU Captain",
            "added": [{"title": summary, "when": "2099-01-01 10:00"}],
            "failed": [],
        }
    )
    dialog = dashboard.CalendarReminderDialog(
        tool,
        [{"title": "作业X", "course_name": "测试课", "deadline_iso": "2099-01-01T10:00:00"}],
    )
    assert dialog._list.count() == 1

    dialog._add_selected()  # checked by default -> run_async -> tool.invoke
    _drain()

    item = dialog._list.item(0)
    assert "已添加" in item.text()
    assert not (item.flags() & dashboard.Qt.ItemFlag.ItemIsUserCheckable)


class RecordingTool(Tool):
    """Records invocations; serves `list` from what `remember` stored."""

    name = "memory"
    description = "memory"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._entries: list[dict[str, str]] = []

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(args)
        if args.get("action") == "remember":
            self._entries.append({"key": "note-x", "value": args.get("text", "")})
            return ToolResult(success=True, data=self._entries[-1])
        if args.get("action") == "list":
            return ToolResult(success=True, data=list(self._entries))
        return ToolResult(success=True, data={})


def test_memory_dialog_remembers_free_text(app: QApplication) -> None:
    # No learner (offline): the sentence is stored verbatim via the keyless
    # `remember` action, synchronously — no worker thread.
    tool = RecordingTool()
    dialog = dashboard.MemoryDialog(tool)
    dialog._note_input.setText("我住在燕园")
    dialog._remember()

    remember_calls = [c for c in tool.calls if c.get("action") == "remember"]
    assert remember_calls == [{"action": "remember", "text": "我住在燕园"}]
    assert dialog._note_input.text() == ""  # cleared after save
    assert dialog._list.count() == 1  # reloaded list shows the new note


def test_memory_dialog_learner_splits_into_facts(
    app: QApplication, tmp_path: Any
) -> None:
    # With a learner (online), the typed sentence is split into clean facts
    # by the LLM and each is stored — driven end-to-end through run_async.
    from src.core.memory import MemoryStore
    from src.core.memory_learn import MemoryLearnService
    from src.llm.base import ChatResponse, LLMProvider
    from src.tools.memory import MemoryTool

    class SplitLLM(LLMProvider):
        name = "split"

        def chat(self, messages: Any, tools: Any = None) -> ChatResponse:
            return ChatResponse(text='["住在燕园", "喜欢用中文交流"]')

    store = MemoryStore(tmp_path / "memory.json")
    tool = MemoryTool(store=store)
    learner = MemoryLearnService(SplitLLM(), store)
    dialog = dashboard.MemoryDialog(tool, learner=learner)

    dialog._note_input.setText("我住在燕园，喜欢用中文交流")
    dialog._remember()
    _drain()

    assert dialog._list.count() == 2  # one row per extracted fact
    assert "已记住 2 条" in dialog._status_label.text()
    assert dialog._note_input.text() == ""


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
