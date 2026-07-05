"""Tool-round limit edits apply live on save (no restart).

The 设置 → 对话设置 tab persists the agent's tool-call round limit and emits
``credentials_changed(["tool_rounds"])``; the dashboard routes that up via
``DashboardPanel.agent_settings_changed``, and ``MainWindow._on_agent_settings_changed``
sets ``max_tool_iterations`` on the *live* agent — no restart, works offline too
(the cap applies to any brain). Mirrors ``test_model_live_apply.py``'s split:
the dashboard half on a real ``DashboardPanel``, the window half against a stub.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.credentials import CredentialStore  # noqa: E402
from src.ui import main_window as mw  # noqa: E402
from src.ui.dashboard import DashboardPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --- dashboard half: the "tool_rounds" sentinel routes up, no card refresh ----
def test_tool_rounds_sentinel_emits_agent_settings_changed(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired: list = []
    refreshed: list = []
    panel.agent_settings_changed.connect(lambda: fired.append(True))
    panel.partial_refresh_requested.connect(lambda keys: refreshed.append(keys))

    panel._on_credentials_changed(["tool_rounds"])
    assert fired == [True]
    assert refreshed == []  # the tool-round limit carries no dashboard card


def test_tool_rounds_mixed_with_card_key(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired: list = []
    refreshed: list = []
    panel.agent_settings_changed.connect(lambda: fired.append(True))
    panel.partial_refresh_requested.connect(lambda keys: refreshed.append(keys))

    panel._on_credentials_changed(["tool_rounds", "treehole_updates"])
    assert fired == [True]
    assert refreshed == [["treehole_updates"]]


# --- window half: the slot applies the persisted limit to the live agent ------
class _AgentStub:
    max_tool_iterations = 8


class _StatusBarStub:
    def showMessage(self, *_a: object, **_k: object) -> None:  # noqa: N802 - Qt API
        pass


class _WindowStub:
    def __init__(self) -> None:
        self._agent = _AgentStub()

    def statusBar(self) -> _StatusBarStub:  # noqa: N802 - Qt API name
        return _StatusBarStub()


def test_window_slot_applies_tool_rounds(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_tool_rounds(15)
    # The slot constructs a bare CredentialStore(); point that at the tmp store.
    monkeypatch.setattr(mw, "CredentialStore", lambda *a, **k: store)

    stub = _WindowStub()
    mw.MainWindow._on_agent_settings_changed(stub)
    assert stub._agent.max_tool_iterations == 15


def test_dashboard_signal_reaches_agent_settings_slot(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """End-to-end: _on_credentials_changed(["tool_rounds"]) → panel signal → slot."""
    store = CredentialStore(tmp_path / "secrets")
    store.save_tool_rounds(3)
    monkeypatch.setattr(mw, "CredentialStore", lambda *a, **k: store)

    panel = DashboardPanel(mode_label="在线")
    stub = _WindowStub()
    panel.agent_settings_changed.connect(
        lambda: mw.MainWindow._on_agent_settings_changed(stub)
    )
    panel._on_credentials_changed(["tool_rounds"])
    assert stub._agent.max_tool_iterations == 3
