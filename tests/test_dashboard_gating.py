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
    # 文档库 reads the committed manifest (no network), so it stays enabled
    # offline — unlike the old online-only 知识库 button it replaced.
    assert panel._knowledge_button.isEnabled()


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
    panel._show_announcement_detail("anything")
    # _show_docbase_dialog is deliberately omitted: doc_search registers
    # offline, so the 文档库 dialog opens rather than bailing at the gate.
    assert len(shown) == 3


def test_account_dialog_opens_offline(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The universal login page is NOT gated on online mode — credentials and
    # model endpoints are configured here even offline. It must construct with
    # offline=True (no treehole tool) and never bail at an info box.
    import src.ui.dashboard as dashboard

    captured: dict[str, object] = {}

    class _Signal:
        def connect(self, *_a: object, **_k: object) -> None:
            pass

    class FakeLoginDialog:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.credentials_changed = _Signal()

        def exec(self) -> int:
            captured["execed"] = True
            return 0

    monkeypatch.setattr(dashboard, "LoginDialog", FakeLoginDialog)
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: shown.append(a[1])
    )
    panel = DashboardPanel(mode_label="离线模式", tools=build_agent(offline=True).tools)
    panel._open_account_dialog()

    assert captured.get("execed") is True
    assert captured.get("offline") is True  # derived from the missing treehole tool
    assert captured.get("auth") is None  # no live auth service offline
    assert shown == []  # opened, not gated


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
