"""Dashboard-side coverage for keeping 树洞消息 in sync with auto-checking.

Two seams, both headless/offscreen:
  * ``DashboardPanel`` accumulates poll results so an unread reply does not
    vanish on the next empty poll, and clears on mark-as-read.
  * ``MainWindow`` starts/stops its auto-sync timer to match the notifier and
    forwards a quiet poll's result into the dashboard. The timer/notifier are
    faked and the window methods are exercised unbound on a stub, so no agent,
    QThread, or launchctl is involved.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import src.ui.dashboard as dashboard  # noqa: E402
from src.core.auto_refresh import AutoRefreshSettings  # noqa: E402
from src.tools.treehole_updates import MIN_NOTIFY_INTERVAL, TreeholeInboxStore  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _update(pid, old, new, comments=None):
    return {
        "pid": pid,
        "old_reply": old,
        "new_reply": new,
        "delta": new - old,
        "text": f"hole {pid}",
        "new_comments": comments or [],
    }


def _panel() -> dashboard.DashboardPanel:
    return dashboard.DashboardPanel(
        mode_label="在线模式", tools=None, treehole_inbox=TreeholeInboxStore()
    )


def test_panel_keeps_unread_after_empty_poll(app: QApplication) -> None:
    panel = _panel()
    panel.set_treehole_updates({"status": "ok", "updates": [_update("1", 2, 3)]})
    assert panel._treehole_data["unread_count"] == 1

    # An empty poll (the common next tick) must NOT blank the card.
    panel.set_treehole_updates({"status": "ok", "message": "暂无树洞新回复", "updates": []})
    assert panel._treehole_data["unread_count"] == 1
    assert [e["pid"] for e in panel._treehole_data["updates"]] == ["1"]


def test_panel_accumulates_across_holes(app: QApplication) -> None:
    panel = _panel()
    panel.set_treehole_updates({"status": "ok", "updates": [_update("1", 0, 1)]})
    panel.set_treehole_updates({"status": "ok", "updates": [_update("2", 0, 2)]})
    pids = {e["pid"] for e in panel._treehole_data["updates"]}
    assert pids == {"1", "2"}
    assert panel._treehole_data["unread_count"] == 3


def test_panel_error_preserves_accumulated_entries(app: QApplication) -> None:
    panel = _panel()
    panel.set_treehole_updates({"status": "ok", "updates": [_update("1", 0, 1)]})
    panel.set_error("treehole_updates", "网络错误")
    assert panel._treehole_data["status"] == "error"
    assert panel._treehole_data["unread_count"] == 1  # entry survived the error


def test_panel_mark_read_clears(app: QApplication) -> None:
    panel = _panel()
    panel.set_treehole_updates({"status": "ok", "updates": [_update("1", 0, 1)]})
    panel._treehole_inbox.clear()
    panel._render_treehole()
    assert panel._treehole_data["unread_count"] == 0


# --- MainWindow auto-sync timer gating (unbound on a stub) -----------------


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False
        self.interval: int | None = None

    def isActive(self) -> bool:  # noqa: N802 - mirrors QTimer API.
        return self.active

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def setInterval(self, ms: int) -> None:  # noqa: N802 - mirrors QTimer API.
        self.interval = ms


class _FakeTools:
    def __init__(self, names: set[str]) -> None:
        self._names = names

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def find(self, name: str):
        return object() if name in self._names else None


def _notify(*, supported=True, enabled=True, logged_in=True, interval=60):
    return SimpleNamespace(
        is_supported=lambda: supported,
        is_enabled=lambda: enabled,
        is_logged_in=lambda: logged_in,
        get_interval=lambda: interval,
    )


def _stub(*, tools=("treehole_updates",), notify=None):
    return SimpleNamespace(
        _agent=SimpleNamespace(tools=_FakeTools(set(tools))),
        _notify_service=notify or _notify(),
        _treehole_sync_timer=_FakeTimer(),
        _treehole_sync_busy=False,
        _treehole_sync_signals=None,
        _dashboard=SimpleNamespace(calls=[], set_treehole_updates=None),
        # `_on_treehole_sync_tick` passes these as run_async callbacks (the fake
        # never calls them); they only need to exist on the stub.
        _on_treehole_sync_done=lambda *a: None,
        _on_treehole_sync_error=lambda *a: None,
    )


def test_reconfigure_starts_timer_when_enabled() -> None:
    stub = _stub(notify=_notify(interval=300))
    MainWindow._reconfigure_treehole_sync(stub)
    assert stub._treehole_sync_timer.active is True
    assert stub._treehole_sync_timer.interval == 300 * 1000


def test_reconfigure_clamps_interval_to_floor() -> None:
    stub = _stub(notify=_notify(interval=5))
    MainWindow._reconfigure_treehole_sync(stub)
    assert stub._treehole_sync_timer.interval == MIN_NOTIFY_INTERVAL * 1000


def test_reconfigure_stops_when_disabled() -> None:
    stub = _stub(notify=_notify(enabled=False))
    stub._treehole_sync_timer.active = True
    MainWindow._reconfigure_treehole_sync(stub)
    assert stub._treehole_sync_timer.active is False


def test_reconfigure_stops_when_tool_unregistered() -> None:
    stub = _stub(tools=())
    stub._treehole_sync_timer.active = True
    MainWindow._reconfigure_treehole_sync(stub)
    assert stub._treehole_sync_timer.active is False


def test_reconfigure_stops_when_not_logged_in() -> None:
    # Enabled but no session: polling would only return auth_required forever.
    stub = _stub(notify=_notify(logged_in=False))
    stub._treehole_sync_timer.active = True
    MainWindow._reconfigure_treehole_sync(stub)
    assert stub._treehole_sync_timer.active is False


def test_sync_tick_dispatches_and_guards_busy(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "src.ui.main_window.run_async",
        lambda fn, *, on_done, on_error: (calls.append((fn, on_done, on_error)), "sig")[1],
    )
    stub = _stub()
    MainWindow._on_treehole_sync_tick(stub)
    assert len(calls) == 1
    assert stub._treehole_sync_busy is True
    assert stub._treehole_sync_signals == "sig"

    # A second tick while a poll is in flight is a no-op.
    MainWindow._on_treehole_sync_tick(stub)
    assert len(calls) == 1


def test_sync_tick_noop_when_tool_unregistered(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "src.ui.main_window.run_async",
        lambda fn, *, on_done, on_error: calls.append(fn),
    )
    stub = _stub(tools=())
    MainWindow._on_treehole_sync_tick(stub)
    assert calls == []
    assert stub._treehole_sync_busy is False


def test_sync_done_forwards_successful_poll() -> None:
    received = []
    stub = _stub()
    stub._treehole_sync_busy = True
    stub._dashboard.set_treehole_updates = received.append
    MainWindow._on_treehole_sync_done(stub, SimpleNamespace(success=True, data={"updates": []}))
    assert stub._treehole_sync_busy is False
    assert received == [{"updates": []}]


def test_sync_done_ignores_failed_poll() -> None:
    received = []
    stub = _stub()
    stub._treehole_sync_busy = True
    stub._dashboard.set_treehole_updates = received.append
    MainWindow._on_treehole_sync_done(stub, SimpleNamespace(success=False, data=None))
    assert stub._treehole_sync_busy is False
    assert received == []


def test_auto_refresh_config_starts_default_interval() -> None:
    labels = []
    stub = SimpleNamespace(
        _auto_refresh_settings=AutoRefreshSettings(),
        _auto_refresh_timer=_FakeTimer(),
        _dashboard=SimpleNamespace(set_auto_refresh_text=labels.append),
    )

    MainWindow._configure_auto_refresh(stub)

    assert stub._auto_refresh_timer.active is True
    assert stub._auto_refresh_timer.interval == 300 * 1000
    assert labels == ["自动刷新 5m"]


def test_auto_refresh_config_stops_when_disabled() -> None:
    labels = []
    stub = SimpleNamespace(
        _auto_refresh_settings=AutoRefreshSettings(enabled=False),
        _auto_refresh_timer=_FakeTimer(),
        _dashboard=SimpleNamespace(set_auto_refresh_text=labels.append),
    )
    stub._auto_refresh_timer.active = True

    MainWindow._configure_auto_refresh(stub)

    assert stub._auto_refresh_timer.active is False
    assert labels == ["自动刷新关"]


def test_auto_refresh_tick_skips_when_refresh_busy() -> None:
    calls = []
    stub = SimpleNamespace(
        _dashboard_refresh_busy=True,
        _start_refresh=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    MainWindow._on_auto_refresh_tick(stub)

    assert calls == []


def test_auto_refresh_tick_starts_silent_refresh() -> None:
    calls = []
    stub = SimpleNamespace(
        _dashboard_refresh_busy=False,
        _start_refresh=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    MainWindow._on_auto_refresh_tick(stub)

    assert calls == [(([],), {"silent": True, "auto_notify": True})]


def test_auto_refresh_first_finish_only_sets_baseline() -> None:
    messages = []
    notifications = []
    labels = []
    stub = SimpleNamespace(
        _refresh_had_success=True,
        _auto_refresh_changes=[object()],
        _auto_refresh_baseline_ready=False,
        _auto_refresh_settings=AutoRefreshSettings(notify_enabled=True),
        _dashboard=SimpleNamespace(set_updated_text=labels.append),
        _auto_refresh_digest=SimpleNamespace(summarize=lambda changes: "摘要"),
        _chat_panel=SimpleNamespace(add_system_message=messages.append),
        _auto_refresh_notifier=SimpleNamespace(notify=notifications.append),
    )

    MainWindow._finish_auto_refresh(stub)

    assert stub._auto_refresh_baseline_ready is True
    assert stub._auto_refresh_changes == []
    assert labels
    assert messages == []
    assert notifications == []
