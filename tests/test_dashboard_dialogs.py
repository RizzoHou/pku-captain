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
