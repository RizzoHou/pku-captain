"""DashboardWorker.refresh must scope to the requested tool keys.

A per-card refresh button (e.g. treehole 刷新, P-Lib 刷新额度) passes a single
key, and the worker must invoke only that tool — not fan out into a full
reload of every card. Empty keys preserve the global header-button behavior of
refreshing everything. Runs headless via Qt's offscreen platform.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.tools.base import Tool, ToolRegistry, ToolResult  # noqa: E402
from src.ui.dashboard_worker import DashboardWorker  # noqa: E402


class _RecordingTool(Tool):
    description = "fake tool"
    parameters_schema: dict[str, Any] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, data={"name": self.name})


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_worker() -> tuple[DashboardWorker, dict[str, _RecordingTool]]:
    names = ("treehole_updates", "plib_materials", "pku3b_announcements", "lecture", "weather")
    tools = {name: _RecordingTool(name) for name in names}
    registry = ToolRegistry()
    for tool in tools.values():
        registry.register(tool)
    worker = DashboardWorker(registry, {name: {} for name in names})
    return worker, tools


def test_refresh_scopes_to_single_key(app: QApplication) -> None:
    worker, tools = _make_worker()
    loaded: list[str] = []
    errored: list[str] = []
    worker.item_loaded.connect(lambda key, _data: loaded.append(key))
    worker.item_error.connect(lambda key, _msg: errored.append(key))

    worker.refresh({}, ["treehole_updates"])

    assert loaded == ["treehole_updates"]
    assert errored == []
    assert tools["treehole_updates"].calls == 1
    assert all(tools[name].calls == 0 for name in tools if name != "treehole_updates")


def test_refresh_empty_keys_refreshes_all(app: QApplication) -> None:
    worker, tools = _make_worker()
    loaded: list[str] = []
    worker.item_loaded.connect(lambda key, _data: loaded.append(key))

    worker.refresh({}, [])

    assert set(loaded) == set(tools)
    assert all(tool.calls == 1 for tool in tools.values())
