"""Offline gating: the dashboard must never reach a network/subprocess tool
that the agent factory left out of the offline tool subset.

Runs headless via Qt's offscreen platform. The leak fix lives in
`DashboardPanel._require_tool` / `_online_tool`, which look the tool up in the
injected `ToolRegistry` and refuse (showing an info box) when it is absent.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from src.core import build_agent  # noqa: E402
from src.tools.base import ToolRegistry  # noqa: E402
from src.ui.dashboard import DashboardPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_offline_dashboard_disables_online_only_buttons(app: QApplication) -> None:
    tools = build_agent(offline=True).tools
    panel = DashboardPanel(mode_label="离线模式", tools=tools)
    assert not panel._treehole_button.isEnabled()
    assert not panel._knowledge_button.isEnabled()


def test_offline_dashboard_refuses_network_dialogs(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: shown.append(args[1])
    )
    panel = DashboardPanel(mode_label="离线模式", tools=build_agent(offline=True).tools)

    # Each handler must bail at the gate (info box) instead of constructing a
    # dialog that would invoke the missing network/subprocess tool.
    panel._show_treehole_dialog()
    panel._show_plib_dialog()
    panel._show_plib_login_dialog()
    panel._show_announcement_detail("anything")
    panel._show_knowledge_dialog()
    assert len(shown) == 5


def test_require_tool_returns_registered_tool(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the tool IS registered (online), the gate passes it through.
    from src.tools import ClockTool

    registry = ToolRegistry()
    registry.register(ClockTool())
    panel = DashboardPanel(mode_label="在线模式", tools=registry)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    assert panel._require_tool("clock", "时钟") is not None
    assert panel._require_tool("plib_materials", "P-Lib") is None
