"""Stop button: swaps with send while a turn runs and reports cancellation.

Runs headless via Qt's offscreen platform.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.ui.chat_panel import ChatPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_idle_shows_send_hides_stop(app: QApplication) -> None:
    # `isHidden()` reflects the explicit show/hide flag — `isVisible()` is False
    # for every child here since the panel is never shown (no parent window).
    panel = ChatPanel()
    panel.set_busy(False)
    assert not panel._send_button.isHidden()
    assert panel._stop_button.isHidden()


def test_busy_swaps_send_for_stop(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_busy(True)
    assert panel._send_button.isHidden()
    assert not panel._stop_button.isHidden()
    assert panel._stop_button.isEnabled()
    # Input is locked while a turn runs.
    assert not panel._input.isEnabled()


def test_stop_click_emits_signal_and_marks_stopping(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_busy(True)
    fired: list[bool] = []
    panel.stop_requested.connect(lambda: fired.append(True))

    panel._emit_stop()

    assert fired == [True]
    # Immediate feedback: button disabled + relabelled so the click is visible.
    assert not panel._stop_button.isEnabled()
    assert panel._stop_button.text() == "停止中…"


def test_busy_false_rearms_stop_button(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_busy(True)
    panel.mark_stopping()
    assert not panel._stop_button.isEnabled()

    panel.set_busy(False)  # turn finished

    assert not panel._send_button.isHidden()
    assert panel._stop_button.isHidden()
    # Re-armed for the next turn.
    assert panel._stop_button.isEnabled()
    assert panel._stop_button.text() == "■ 停止"
