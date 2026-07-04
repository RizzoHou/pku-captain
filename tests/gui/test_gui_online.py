"""Opt-in online GUI smoke — drive the *live* app like a real person.

Skipped by default (like ``scripts/smoke_*.py``) so ``pytest tests/`` stays
network-free. Set ``PKU_CAPTAIN_GUI_ONLINE=1`` to run it against the developer's
real ``secrets/``: it builds a live ``MainWindow(offline=False)``, asserts it did
**not** silently fall back to offline, then drives a real chat turn (costs
tokens) and a real dashboard refresh (hits PKU endpoints) through the worker
threads, exactly as the offline smoke does.

    PKU_CAPTAIN_GUI_ONLINE=1 .venv/bin/pytest tests/gui/test_gui_online.py -s

Uses the developer's real credentials + data intentionally — no tmp redirect —
so it exercises the same paths the captain sees on his Mac.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PKU_CAPTAIN_GUI_ONLINE"),
    reason="online GUI smoke is opt-in; set PKU_CAPTAIN_GUI_ONLINE=1 to run against real secrets/",
)


def test_online_gui_smoke(qapp, wait_for_signal, wait_until, assistant_texts, close_window):
    """Full live round-trip through the real MainWindow. Generous timeouts."""
    from src.ui.main_window import MainWindow

    window = MainWindow(offline=False)
    try:
        # Did online mode actually take effect? build_agent silently falls back
        # to offline on any online-init failure (missing model key, network),
        # so a green-but-offline run would be a false positive — fail loudly.
        assert window._effective_offline is False, (
            "MainWindow silently fell back to offline — check secrets/models.json "
            "(text-role API key) and network connectivity."
        )

        # Let the live startup refresh settle (real endpoints, so be patient).
        wait_until(lambda: not window._dashboard_refresh_busy, timeout_ms=60000)

        # Real chat turn (costs tokens) through the AgentWorker thread.
        fired = wait_for_signal(
            window._agent_worker.finished,
            timeout_ms=180000,
            trigger=lambda: window._chat_panel.send_requested.emit("用一句话介绍北京大学。"),
        )
        assert fired, "live agent turn did not finish within the timeout"
        qapp.processEvents()
        texts = assistant_texts(window)
        assert texts and any(t.strip() for t in texts), "no assistant reply rendered"

        # Real dashboard refresh against live tools through the DashboardWorker thread.
        assert wait_until(lambda: not window._dashboard_refresh_busy, timeout_ms=60000)
        fired = wait_for_signal(
            window._dashboard_worker.finished,
            timeout_ms=180000,
            trigger=lambda: window._dashboard.refresh_requested.emit(),
        )
        assert fired, "live dashboard refresh did not finish within the timeout"
    finally:
        close_window(window, qapp)
