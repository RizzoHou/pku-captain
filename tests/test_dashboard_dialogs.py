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
from PyQt6.QtTest import QTest  # noqa: E402
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
    dashboard.AnnouncementDetailDialog(tool, "id-1")
    dashboard.CalendarReminderDialog(tool, [])
    dashboard.MemoryDialog(tool)
    dashboard.DocBaseDialog(tool, None)
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


def test_docbase_read_path_reaches_result_dialog(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Drive the 让 Captain 阅读 glue end-to-end: select a doc → question prompt
    # → run_async(doc_read) → _on_read_done → DocReadResultDialog. Construction
    # tests cover the widgets; this covers the wiring between them.
    doc = {
        "volume": "本科培养方案2025-理科卷",
        "breadcrumb": [],
        "title": "基础数学",
        "pages": 6,
        "path": "x.pdf",
        "abs_path": "/tmp/x.pdf",
    }
    search = FakeTool([doc])  # invoke({}) → browse payload (one leaf)

    class FakeReader:
        def read(
            self,
            path: str,
            question: str | None = None,
            pages: str | None = None,
        ) -> ToolResult:
            return ToolResult(
                success=True,
                data={
                    "title": "基础数学",
                    "volume": "本科培养方案2025-理科卷",
                    "pages_read": [1, 2],
                    "total_pages": 6,
                    "answer": "毕业总学分：138",
                    "note": "",
                },
            )

    read = FakeReader()
    monkeypatch.setattr(
        dashboard.QInputDialog, "getText", lambda *a, **k: ("毕业总学分？", True)
    )
    captured: dict[str, Any] = {}

    class FakeResultDialog:
        def __init__(self, data: Any, parent: Any = None) -> None:
            captured["data"] = data

        def exec(self) -> int:
            captured["execed"] = True
            return 0

    monkeypatch.setattr(dashboard, "DocReadResultDialog", FakeResultDialog)

    dlg = dashboard.DocBaseDialog(search, read)
    leaf = dlg._tree.topLevelItem(0).child(0)
    dlg._tree.setCurrentItem(leaf)
    dlg._read_doc()
    _drain()

    assert captured.get("execed") is True
    assert captured["data"]["answer"] == "毕业总学分：138"


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


def test_open_external_url_prefers_safari_on_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(cmd: list[str], **_: object) -> Result:
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(dashboard.sys, "platform", "darwin")
    monkeypatch.setattr(dashboard.subprocess, "run", fake_run)

    assert dashboard._open_external_url("https://example.com")
    assert calls == [["open", "-a", "Safari", "https://example.com"]]


def test_open_external_url_falls_back_to_qdesktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    monkeypatch.setattr(dashboard.sys, "platform", "linux")
    monkeypatch.setattr(
        dashboard.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )

    assert dashboard._open_external_url("https://example.com/fallback")
    assert opened == ["https://example.com/fallback"]


def test_clickable_rows_open_linked_sections(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(dashboard, "_open_external_url", lambda url: opened.append(url) or True)

    dean_row = dashboard._dean_update_row(
        {
            "title": "本科生学籍管理办法",
            "source_label": "校级规章",
            "date": "2026-06-05",
            "url": "https://dean.pku.edu.cn/web/rules/15",
        }
    )
    treehole_row = dashboard._treehole_row({"pid": 123, "delta": 1, "text": "x"})
    dean_row.show()
    treehole_row.show()

    QTest.mouseClick(dean_row, dashboard.Qt.MouseButton.LeftButton)
    QTest.mouseClick(treehole_row, dashboard.Qt.MouseButton.LeftButton)

    assert opened == [
        "https://dean.pku.edu.cn/web/rules/15",
        dashboard.TREEHOLE_WEB_URL,
    ]


def test_pku3b_rows_open_resolved_links_and_announcements_request_detail(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    detail_items: list[dict[str, object]] = []
    monkeypatch.setattr(
        dashboard, "_open_external_url", lambda url: opened.append(url) or True
    )

    todo_row = dashboard._todo_row(
        {
            "title": "作业十七",
            "course_name": "程序设计实习",
            "deadline_iso": "2099-01-01T10:00:00",
            "submit_url": "https://course.pku.edu.cn/webapps/assignment/uploadAssignment",
            "url": "https://course.pku.edu.cn/webapps/blackboard/content/listContent.jsp",
        }
    )
    announcement_card = dashboard.AnnouncementsCard()
    announcement_button = announcement_card._announcement_row(
        {
            "course": "人工智能基础",
            "title": "复习课通知",
            "url": "https://course.pku.edu.cn/webapps/blackboard/content/launchLink.jsp",
        }
    )
    announcement_card.detail_requested.connect(detail_items.append)
    fallback_button = announcement_card._announcement_row(
        {"course": "未知课程", "title": "无链接通知"}
    )
    todo_row.show()
    announcement_button.show()
    fallback_button.show()

    QTest.mouseClick(todo_row, dashboard.Qt.MouseButton.LeftButton)
    QTest.mouseClick(announcement_button, dashboard.Qt.MouseButton.LeftButton)
    QTest.mouseClick(fallback_button, dashboard.Qt.MouseButton.LeftButton)

    assert opened == ["https://course.pku.edu.cn/webapps/assignment/uploadAssignment"]
    assert [item["title"] for item in detail_items] == ["复习课通知", "无链接通知"]


def test_announcements_history_accumulates_and_opens_links(
    app: QApplication,
) -> None:
    card = dashboard.AnnouncementsCard()
    card.set_announcements(
        {
            "announcements": [
                {
                    "id": "a1",
                    "course": "程序设计实习",
                    "title": "通知一",
                    "url": "https://course.pku.edu.cn/notice/a1",
                }
            ]
        }
    )
    card.set_announcements(
        {
            "announcements": [
                {
                    "id": "a1",
                    "course": "程序设计实习",
                    "title": "通知一",
                    "url": "https://course.pku.edu.cn/notice/a1",
                },
                {
                    "id": "a2",
                    "course": "人工智能基础",
                    "title": "通知二",
                    "url": "https://course.pku.edu.cn/notice/a2",
                },
            ]
        }
    )

    assert [item["id"] for item in card._history_items] == ["a1", "a2"]

    dialog = dashboard.AnnouncementsHistoryDialog(card._history_items)
    detail_items: list[dict[str, object]] = []
    dialog.detail_requested.connect(detail_items.append)
    buttons = [
        button
        for button in dialog.findChildren(dashboard.QPushButton, "ListRowButton")
        if "通知" in button.text()
    ]
    assert len(buttons) == 2

    buttons[1].show()
    QTest.mouseClick(buttons[1], dashboard.Qt.MouseButton.LeftButton)

    assert [item["id"] for item in detail_items] == ["a2"]


def test_announcement_detail_dialog_opens_external_page(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        dashboard, "_open_external_url", lambda url: opened.append(url) or True
    )
    tool = FakeTool(
        {
            "announcement": {
                "id": "a1",
                "course": "程序设计实习",
                "title": "通知一",
                "posted_at": "2026-06-06",
                "body": "正文内容",
            }
        }
    )
    dialog = dashboard.AnnouncementDetailDialog(
        tool,
        {
            "id": "a1",
            "course": "程序设计实习",
            "title": "通知一",
            "url": "https://course.pku.edu.cn/notice/a1",
        },
    )
    _drain()

    button = dialog.findChild(dashboard.QPushButton, "SecondaryButton")
    assert button is not None
    button.click()

    assert opened == ["https://course.pku.edu.cn/notice/a1"]


def test_announcement_detail_dialog_falls_back_to_stored_fields_on_failure(
    app: QApplication,
) -> None:
    # A history row's announcement can vanish from 教学网 entirely; the dialog
    # must degrade to the row's own stored fields, not a bare not-found error.
    class NotFoundTool(FakeTool):
        def invoke(self, args: dict[str, Any]) -> ToolResult:
            return ToolResult(
                success=False, error="announcement with id a9 not found"
            )

    dialog = dashboard.AnnouncementDetailDialog(
        NotFoundTool(),
        {
            "id": "a9",
            "course": "程序设计实习",
            "title": "已下线的通知",
            "posted_at": "2026-03-01",
        },
    )
    _drain()

    body = dialog._body_label.text()
    assert "已下线的通知" in body
    assert "程序设计实习" in body
    assert "2026-03-01" in body
    assert "not found" in body  # failure reason stays visible


def test_announcements_history_shows_full_returned_list(app: QApplication) -> None:
    # 历史通知 keeps every announcement; 最近 windows to those posted within the
    # last month (by posted_date). Give 3 items recent dates and the rest an
    # old one, so the card shows 3 recent but history still holds all 65.
    from datetime import date, timedelta

    today = date.today()
    recent_iso = (today - timedelta(days=3)).isoformat()
    old_iso = (today - timedelta(days=200)).isoformat()
    card = dashboard.AnnouncementsCard()
    announcements = [
        {
            "id": f"a{index}",
            "course": "中国近现代史纲要",
            "title": f"通知 {index}",
            "url": f"https://course.pku.edu.cn/notice/a{index}",
            "posted_date": recent_iso if index < 3 else old_iso,
        }
        for index in range(65)
    ]

    card.set_announcements(
        {"announcements": announcements, "total_reported": len(announcements)}
    )
    dialog = dashboard.AnnouncementsHistoryDialog(card.history_items())
    buttons = dialog.findChildren(dashboard.QPushButton, "ListRowButton")

    assert card._summary_label.text() == "最近 3 条 / 总计 65 条"
    assert len(card.history_items()) == 65
    assert len(buttons) == 65


def test_schedule_card_does_not_open_teaching_web(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(dashboard, "_open_external_url", lambda url: opened.append(url) or True)

    card = dashboard.ScheduleCard()
    card.resize(360, 260)
    card.show()

    QTest.mouseClick(card, dashboard.Qt.MouseButton.LeftButton, pos=card.rect().center())

    assert opened == []


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
