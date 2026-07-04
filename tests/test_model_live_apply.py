"""Model-config edits apply live on save (no restart) — Task 02.

The 账号中心 → 模型配置 tab persists a role's endpoint / model / key and emits
``credentials_changed(["models", ...])``; the dashboard routes that up via the
new ``DashboardPanel.model_config_changed`` signal, and
``MainWindow._on_model_config_changed`` rebuilds the *active* role's chat brain
from the new on-disk config — without restarting the app.

Runs headless via Qt's offscreen platform. The dashboard half runs on a real
``DashboardPanel``; the window half drives ``MainWindow._on_model_config_changed``
against a lightweight stub (the slot touches only a handful of ``self`` fields),
with ``apply_chat_model`` / ``available_chat_models`` monkeypatched to record
calls — the exact pattern ``test_chat_panel_segments.py`` uses for the wiring.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.ui import main_window as mw  # noqa: E402
from src.ui.chat_panel import ChatPanel  # noqa: E402
from src.ui.dashboard import DashboardPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


# --- dashboard half: the "models" sentinel routes up, others don't ------------


def _recorders(panel: DashboardPanel) -> tuple[list, list]:
    fired: list = []
    refreshed: list = []
    panel.model_config_changed.connect(lambda: fired.append(True))
    panel.partial_refresh_requested.connect(lambda keys: refreshed.append(keys))
    return fired, refreshed


def test_models_key_emits_model_config_changed(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired, refreshed = _recorders(panel)
    panel._on_credentials_changed(["models"])
    assert fired == [True]
    assert refreshed == []  # a model role carries no live dashboard card


def test_non_models_key_still_refreshes_its_card(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired, refreshed = _recorders(panel)
    panel._on_credentials_changed(["treehole_updates"])
    assert fired == []  # no model apply for a credential-card sentinel
    assert refreshed == [["treehole_updates"]]


def test_network_sentinel_refreshes_all_cards(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired, refreshed = _recorders(panel)
    panel._on_credentials_changed(["network"])
    assert fired == []
    assert refreshed == [
        ["treehole_updates", "plib_materials", "pku3b_assignments", "pku3b_announcements"]
    ]


def test_mixed_keys_emit_both(app: QApplication) -> None:
    panel = DashboardPanel(mode_label="离线")
    fired, refreshed = _recorders(panel)
    panel._on_credentials_changed(["models", "treehole_updates"])
    assert fired == [True]
    assert refreshed == [["treehole_updates"]]


# --- window half: the slot rebuilds the active brain from disk -----------------


class _AgentStub:
    def __init__(self) -> None:
        self.llm = object()


class _StatusBarStub:
    def showMessage(self, *_a: object, **_k: object) -> None:  # noqa: N802 - Qt API name
        pass


class _WindowStub:
    """Minimal stand-in: the slot reads only these fields / helpers."""

    def __init__(
        self,
        *,
        offline: bool,
        busy: bool,
        model_key: str | None,
        model_labels: dict,
        panel: ChatPanel,
    ) -> None:
        self._effective_offline = offline
        self._busy = busy
        self._model_key = model_key
        self._model_labels = model_labels
        self._agent = _AgentStub()
        self._chat_panel = panel
        self.begin_new_session_calls = 0
        self.refresh_meter_calls = 0

    def _begin_new_session(self) -> None:
        self.begin_new_session_calls += 1

    def _refresh_context_meter(self, payload: dict | None = None) -> None:
        self.refresh_meter_calls += 1

    def statusBar(self) -> _StatusBarStub:  # noqa: N802 - Qt API name
        return _StatusBarStub()


@pytest.fixture
def record_apply(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_apply(agent: object, key: str, *, offline: bool) -> None:
        calls.append((key, offline))

    monkeypatch.setattr(mw, "apply_chat_model", fake_apply)
    return calls


def _set_available(monkeypatch: pytest.MonkeyPatch, models: list) -> None:
    monkeypatch.setattr(mw, "available_chat_models", lambda *, offline: list(models))


def test_same_role_rebuild_keeps_conversation(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, record_apply: list
) -> None:
    _set_available(monkeypatch, [("text", "文本模型"), ("visual", "视觉模型")])
    stub = _WindowStub(
        offline=False,
        busy=False,
        model_key="text",
        model_labels={"text": "文本模型"},
        panel=ChatPanel(),
    )
    mw.MainWindow._on_model_config_changed(stub)
    assert record_apply == [("text", False)]  # active role rebuilt from disk
    assert stub.begin_new_session_calls == 0  # same role → no reset
    assert stub.refresh_meter_calls == 1  # meter re-reads the new window
    assert stub._model_key == "text"
    # A role that just became configured now shows in the switcher labels.
    assert stub._model_labels == {"text": "文本模型", "visual": "视觉模型"}


def test_lost_key_falls_back_and_resets(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, record_apply: list
) -> None:
    # Active role is visual, but only text is configured after the edit.
    _set_available(monkeypatch, [("text", "文本模型")])
    stub = _WindowStub(
        offline=False,
        busy=False,
        model_key="visual",
        model_labels={"text": "文本模型", "visual": "视觉模型"},
        panel=ChatPanel(),
    )
    mw.MainWindow._on_model_config_changed(stub)
    assert record_apply == [("text", False)]  # fell back to a configured role
    assert stub.begin_new_session_calls == 1  # a different brain resets the chat
    assert stub._model_key == "text"


def test_busy_guard_does_not_swap_brain(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, record_apply: list
) -> None:
    _set_available(monkeypatch, [("text", "文本模型"), ("visual", "视觉模型")])
    stub = _WindowStub(
        offline=False,
        busy=True,
        model_key="text",
        model_labels={"text": "文本模型"},
        panel=ChatPanel(),
    )
    mw.MainWindow._on_model_config_changed(stub)
    assert record_apply == []  # brain never swapped mid-turn
    assert stub.begin_new_session_calls == 0
    assert stub._model_key == "text"


def test_offline_is_noop(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, record_apply: list
) -> None:
    _set_available(monkeypatch, [])
    stub = _WindowStub(
        offline=True,
        busy=False,
        model_key=None,
        model_labels={},
        panel=ChatPanel(),
    )
    mw.MainWindow._on_model_config_changed(stub)
    assert record_apply == []  # Echo brain offline — nothing to rebuild
    assert stub.begin_new_session_calls == 0


def test_apply_failure_keeps_current_brain(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_available(monkeypatch, [])  # degenerate: nothing configured online

    def boom(agent: object, key: str, *, offline: bool) -> None:
        raise FileNotFoundError("no key")

    monkeypatch.setattr(mw, "apply_chat_model", boom)
    stub = _WindowStub(
        offline=False,
        busy=False,
        model_key="text",
        model_labels={"text": "文本模型"},
        panel=ChatPanel(),
    )
    mw.MainWindow._on_model_config_changed(stub)
    assert stub._model_key == "text"  # unchanged — old brain still in place
    assert stub.begin_new_session_calls == 0


def test_dashboard_signal_reaches_window_slot(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, record_apply: list
) -> None:
    """End-to-end: _on_credentials_changed(["models"]) → panel signal → slot."""
    _set_available(monkeypatch, [("text", "文本模型"), ("visual", "视觉模型")])
    panel = DashboardPanel(mode_label="在线")
    stub = _WindowStub(
        offline=False,
        busy=False,
        model_key="text",
        model_labels={"text": "文本模型"},
        panel=ChatPanel(),
    )
    panel.model_config_changed.connect(
        lambda: mw.MainWindow._on_model_config_changed(stub)
    )
    panel._on_credentials_changed(["models"])
    assert record_apply == [("text", False)]
