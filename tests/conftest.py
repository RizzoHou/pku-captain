"""Shared headless-GUI test harness for PKU Captain.

The rest of the suite tests leaf widgets or drives unbound handlers over
hand-rolled stubs; nothing here builds a *whole* ``MainWindow`` and pumps the
three real worker ``QThread``s the way the app runs on the captain's Mac. This
conftest is the backbone that makes that possible, so an agent working offline
can catch live-GUI breakage. See ``tests/gui/README.md`` for how to add a test.

Design constraints:

* **No pytest-qt.** It is deliberately not a dependency. The one primitive the
  suite lacked — block until a Qt signal fires while pumping the event loop — is
  implemented here as :func:`_wait_for_signal` / :func:`_wait_until`.
* **Hermetic offline.** The :func:`tmp_secrets` fixture points the app's whole
  on-disk state (``secrets/`` *and* ``data/``) at a tmp tree, so a headless run
  never reads the developer's real credentials nor writes a stray session /
  cache / inbox file into the real ``data/`` the running app reads back.

Helpers are exposed as fixtures (``wait_for_signal``, ``wait_until``,
``assistant_texts``, ``close_window``) so tests get them without importing this
module by name.
"""

from __future__ import annotations

import os

# Qt must select the headless platform before the first QApplication / widget
# import. Idempotent with the per-file ``setdefault``s the older Qt tests do.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable  # noqa: E402 - must follow the env setdefault
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import QEventLoop, QThreadPool, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QLabel  # noqa: E402


# --------------------------------------------------------------------------- #
# Event-loop primitives (the thing the pre-existing suite could not do).
# --------------------------------------------------------------------------- #
def _wait_for_signal(
    signal: Any,
    timeout_ms: int = 5000,
    *,
    trigger: Callable[[], None] | None = None,
) -> bool:
    """Block until ``signal`` fires, pumping the event loop, or time out.

    Returns ``True`` if the signal fired and ``False`` on timeout — a test
    asserts on the return so a worker thread that never emits fails loudly
    instead of passing vacuously.

    ``trigger`` (optional) is invoked *after* the signal is connected but
    *before* the loop spins, closing the connect-then-emit race for a signal a
    worker emits almost immediately (e.g. emit ``refresh_requested`` and then
    wait on the worker's ``finished``). A cross-thread ``queued`` emit is only
    delivered inside ``loop.exec()``, so it can never be missed here.
    """
    loop = QEventLoop()
    fired = {"value": False}

    def on_fire(*_args: Any) -> None:
        fired["value"] = True
        loop.quit()

    signal.connect(on_fire)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    try:
        if trigger is not None:
            trigger()
        # A same-thread (direct) emit inside ``trigger`` may already have fired
        # on_fire; only spin the loop if we are still waiting, so exec() cannot
        # block forever on a signal that has already come and gone.
        if not fired["value"]:
            loop.exec()
    finally:
        timer.stop()
        try:
            signal.disconnect(on_fire)
        except (TypeError, RuntimeError):
            pass
    return fired["value"]


def _wait_until(
    predicate: Callable[[], bool],
    timeout_ms: int = 5000,
    *,
    interval_ms: int = 10,
) -> bool:
    """Pump the event loop until ``predicate()`` is true, or time out.

    For waiting on state that is not a single signal — a busy flag clearing, a
    rendered-bubble count reaching N. Returns whether the predicate held.
    """
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(interval_ms)
    poll.timeout.connect(lambda: predicate() and loop.quit())
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout_ms)
    try:
        loop.exec()
    finally:
        poll.stop()
        deadline.stop()
    return predicate()


def _assistant_bubble_texts(window: Any) -> list[str]:
    """Rendered body text of every assistant bubble in the chat panel.

    Reads what the user actually sees: each finalized reply is a
    ``QFrame#MessageBubble`` with ``messageRole == "assistant"`` wrapping a
    ``QLabel#MessageText``. Offscreen disables the WebEngine math view, so the
    body is always a ``QLabel`` (a ``MathMessageView`` would not match here).
    """
    texts: list[str] = []
    for bubble in window._chat_panel.findChildren(QFrame, "MessageBubble"):
        if bubble.property("messageRole") != "assistant":
            continue
        body = bubble.findChild(QLabel, "MessageText")
        if body is not None:
            texts.append(body.text())
    return texts


def _close_window(window: Any, app: QApplication) -> None:
    """Tear a MainWindow down the way the app does, then drain stragglers.

    ``QWidget.close()`` delivers ``closeEvent`` synchronously — it stops the
    timers, persists the session, and ``quit()`` + ``wait()``s the three worker
    threads. Draining the global thread pool afterwards keeps a late
    ``run_async`` callback (e.g. the session titler) from firing into a
    torn-down window.
    """
    window.close()
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    window.deleteLater()
    app.processEvents()


# --------------------------------------------------------------------------- #
# Fixtures.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """The one process-wide ``QApplication`` (reused if a test already made one)."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wait_for_signal() -> Callable[..., bool]:
    """Expose :func:`_wait_for_signal` to tests."""
    return _wait_for_signal


@pytest.fixture
def wait_until() -> Callable[..., bool]:
    """Expose :func:`_wait_until` to tests."""
    return _wait_until


@pytest.fixture
def assistant_texts() -> Callable[[Any], list[str]]:
    """Expose :func:`_assistant_bubble_texts` to tests."""
    return _assistant_bubble_texts


@pytest.fixture
def close_window() -> Callable[[Any, QApplication], None]:
    """Expose :func:`_close_window` to tests (used by the online GUI test)."""
    return _close_window


@pytest.fixture
def tmp_secrets(tmp_path, monkeypatch):
    """Redirect the app's whole on-disk state (``secrets/`` + ``data/``) to tmp.

    Two jobs:

    * **Credentials** — ``build_agent`` and MainWindow's startup diagnostics
      never touch the developer's real ``secrets/``. Both the documented
      ``bootstrap._store`` seam and the bare ``CredentialStore()`` default dir
      (used by the diagnostics) are redirected.
    * **App data** — a headless MainWindow never writes a stray session file,
      dashboard cache, or inbox into the real ``data/`` the running app reads.

    Implementation gotcha worth knowing when extending this: every store binds
    its ``_DEFAULT_*`` path as a *default argument* at import time, so patching
    those module constants is a no-op. MainWindow constructs the stores with no
    args, so we instead redirect the *late-bound* names it references at call
    time — the imported factory/class in MainWindow's own namespace, or a
    module ``_REPO_ROOT`` used inside a function body. **Add a line here
    whenever a new app-state sink is wired into MainWindow.**
    """
    import src.core.bootstrap as bootstrap
    import src.core.credentials as credentials
    import src.tools.treehole_updates as treehole_updates
    import src.ui.main_window as main_window
    from src.core.announcement_history import AnnouncementHistoryStore
    from src.core.auto_refresh import AutoRefreshSettingsStore
    from src.core.credentials import CredentialStore
    from src.core.dashboard_cache import DashboardCache
    from src.core.memory import MemoryStore
    from src.core.session_store import SessionStore

    root = tmp_path
    secrets_dir = root / "secrets"
    data_dir = root / "data"
    secrets_dir.mkdir()
    data_dir.mkdir()

    # -- credentials ------------------------------------------------------
    monkeypatch.setattr(
        bootstrap, "_store", lambda: CredentialStore(secrets_dir=secrets_dir)
    )
    monkeypatch.setattr(credentials, "_REPO_ROOT", root)  # bare CredentialStore()

    # -- data writers (redirect the caller-namespace names) ---------------
    # treehole / dean inbox stores use MainWindow's own _REPO_ROOT for their
    # explicit paths; the treehole notifier uses its module's _REPO_ROOT.
    monkeypatch.setattr(main_window, "_REPO_ROOT", root)
    monkeypatch.setattr(treehole_updates, "_REPO_ROOT", root)
    monkeypatch.setattr(
        main_window, "build_session_store", lambda: SessionStore(data_dir / "sessions")
    )
    monkeypatch.setattr(
        main_window,
        "build_dashboard_cache",
        lambda: DashboardCache(data_dir / "dashboard_cache"),
    )
    monkeypatch.setattr(
        main_window,
        "AnnouncementHistoryStore",
        lambda: AnnouncementHistoryStore(data_dir / "announcement_history.json"),
    )
    monkeypatch.setattr(
        main_window,
        "AutoRefreshSettingsStore",
        lambda: AutoRefreshSettingsStore(data_dir / "auto_refresh_settings.json"),
    )
    # build_agent constructs the MemoryStore itself; redirect it at the source.
    monkeypatch.setattr(
        bootstrap, "MemoryStore", lambda *a, **k: MemoryStore(data_dir / "memory.json")
    )
    return root


@pytest.fixture
def main_window(qapp, tmp_secrets):
    """A fully-constructed **offline** MainWindow, torn down cleanly.

    Building it is the real boot path: it starts the three worker QThreads,
    seeds the dashboard from (now-empty) cache, and kicks a silent background
    refresh. We let that startup refresh settle so a test begins from a
    quiescent window, then yield. Teardown goes through ``closeEvent``.
    """
    from src.ui.main_window import MainWindow

    window = MainWindow(offline=True)
    # Let the queued startup refresh drain so a test's own refresh does not
    # no-op against an in-flight one. Best-effort — a test drives its own wait.
    _wait_until(lambda: not window._dashboard_refresh_busy, timeout_ms=10000)
    try:
        yield window
    finally:
        _close_window(window, qapp)
