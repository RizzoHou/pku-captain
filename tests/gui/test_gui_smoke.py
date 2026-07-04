"""Flagship offline end-to-end GUI smoke test.

Builds the *real* ``MainWindow`` headless and drives it the way a person would —
send a chat message and pump the ``AgentWorker`` thread until the reply renders,
then trigger a dashboard refresh and pump the ``DashboardWorker`` thread. This
is the coverage the suite lacked: the queued ``invokeMethod`` → worker thread →
signal → main-window slot round-trip that leaf-widget tests never exercise.

Everything runs offline (``EchoLLMProvider`` + the offline tool subset), so it is
deterministic and network-free. It asserts only on **stable seams** — never on a
specific header button or label, which sibling tasks add/remove/rename.
"""

from __future__ import annotations


def test_main_window_builds_offline(main_window):
    """The whole window constructs, seeds the dashboard, and is effectively
    offline — without raising (the fixture already built + settled it)."""
    window = main_window
    assert window._effective_offline is True
    assert window._chat_panel is not None
    assert window._dashboard is not None
    # The three worker threads are live (agent / dashboard / workflow).
    assert window._agent_thread.isRunning()
    assert window._dashboard_thread.isRunning()
    assert window._workflow_thread.isRunning()


def test_chat_turn_through_agent_thread(main_window, qapp, wait_for_signal, assistant_texts):
    """Drive a real chat turn end-to-end and assert the reply rendered.

    Emitting ``send_requested`` is the human action (it is what pressing Enter /
    发送 does). The turn runs on the ``AgentWorker`` QThread; we wait on its
    ``finished`` signal while pumping the loop. ``EchoLLMProvider`` echoes the
    message deterministically, so the finalized assistant bubble must contain it.
    """
    window = main_window
    message = "hello from the offline gui smoke test"

    fired = wait_for_signal(
        window._agent_worker.finished,
        timeout_ms=15000,
        trigger=lambda: window._chat_panel.send_requested.emit(message),
    )
    assert fired, "AgentWorker.finished never fired — the agent thread did not run the turn"
    qapp.processEvents()  # flush the queued `final` event's render

    texts = assistant_texts(window)
    assert texts, "no assistant bubble rendered after the turn"
    # Offline Echo replies with `echo: <message>`; assert both the marker and the
    # round-tripped user text made it through the thread hop into the bubble.
    assert any("echo" in t for t in texts), f"reply is not the offline echo: {texts!r}"
    assert any("offline gui smoke test" in t for t in texts), (
        f"user message did not round-trip into the reply: {texts!r}"
    )
    # Busy state cleared on the GUI thread once the turn finished.
    assert window._busy is False


def test_dashboard_refresh_through_worker_thread(main_window, wait_for_signal, wait_until):
    """Drive a real dashboard refresh through the ``DashboardWorker`` QThread.

    Emitting ``refresh_requested`` is the header 刷新 button's action. Offline the
    networked tools are unregistered, so each card reports an error rather than
    data — that is fine; the seam under test is that the refresh *cycle* runs on
    the worker thread and completes (``finished``) without crashing the window.
    """
    window = main_window
    # Make sure the startup refresh is done, else our refresh no-ops on busy.
    assert wait_until(lambda: not window._dashboard_refresh_busy, timeout_ms=10000)

    fired = wait_for_signal(
        window._dashboard_worker.finished,
        timeout_ms=10000,
        trigger=lambda: window._dashboard.refresh_requested.emit(),
    )
    assert fired, "DashboardWorker.finished never fired — the dashboard thread did not run"
    assert window._dashboard_refresh_busy is False


def test_two_turns_render_distinct_bubbles(main_window, qapp, wait_for_signal, assistant_texts):
    """A second turn adds a second assistant bubble (no clobbering of the first).

    Guards the multi-turn render path — two full thread round-trips in one window
    session, each producing its own bubble.
    """
    window = main_window
    for token in ("first probe message", "second probe message"):
        fired = wait_for_signal(
            window._agent_worker.finished,
            timeout_ms=15000,
            trigger=lambda t=token: window._chat_panel.send_requested.emit(t),
        )
        assert fired, f"turn for {token!r} did not finish"
        qapp.processEvents()

    texts = assistant_texts(window)
    assert len(texts) >= 2, f"expected two assistant bubbles, got {texts!r}"
    assert any("first probe message" in t for t in texts)
    assert any("second probe message" in t for t in texts)
