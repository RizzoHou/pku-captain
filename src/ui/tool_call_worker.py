"""Run a blocking callable off the GUI thread and deliver the result back on it.

Dashboard dialogs call tools that touch the network or a subprocess (P-Lib,
treehole auth, announcement detail, knowledge search). Running those inline on
the GUI thread freezes the window, so they go through `run_async`. The work runs
on Qt's global thread pool; the result/error are emitted via signals, which —
because the signals object is created on the GUI thread — are delivered back on
the GUI thread, where touching widgets is safe.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class _AsyncSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class _AsyncTask(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _AsyncSignals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI as a message
            self._signals.failed.emit(str(exc))
            return
        self._signals.finished.emit(result)


def run_async(
    fn: Callable[[], Any],
    *,
    on_done: Callable[[object], None],
    on_error: Callable[[str], None],
) -> _AsyncSignals:
    """Run ``fn`` on a worker thread; deliver result/error on the caller's thread.

    Connect ``on_done`` / ``on_error`` to **bound methods of a QObject** (e.g. a
    dialog) so Qt auto-disconnects them if that object is destroyed mid-flight —
    this is what makes closing a dialog while a call is in progress safe.
    """
    signals = _AsyncSignals()
    signals.finished.connect(on_done)
    signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(_AsyncTask(fn, signals))
    return signals
