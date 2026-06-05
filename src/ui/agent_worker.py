"""Qt worker that runs Agent turns off the GUI thread.

The integration contract requires every blocking agent turn to run in a
QThread. This QObject exposes a single queued slot for user messages and
forwards AgentEvent objects back to the main window through signals.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..core import Agent


class AgentWorker(QObject):
    """Run one Agent turn at a time and emit GUI-friendly progress signals."""

    agent_event = pyqtSignal(object)
    finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent
        self._busy = False
        # Cooperative cancellation. The worker thread is blocked inside
        # `agent.turn` for the whole turn, so a queued slot would never run
        # until the turn ended — `request_cancel` must instead flip a
        # thread-safe flag the running turn polls. `threading.Event` is exactly
        # that, and is safe to set directly from the GUI thread.
        self._cancel_event = threading.Event()

    @pyqtSlot(str)
    def run_turn(self, user_message: str) -> None:
        """Run ``Agent.turn`` and forward each event to the GUI thread."""
        text = user_message.strip()
        if not text:
            self.finished.emit()
            return
        if self._busy:
            self.error_occurred.emit("AgentWorker is already processing a turn.")
            self.finished.emit()
            return

        # Drop any cancel left set by a previous turn (or a click that landed
        # after the turn already finished) so it can't instantly kill this one.
        self._cancel_event.clear()
        self._busy = True
        try:
            for event in self.agent.turn(text, cancelled=self._cancel_event.is_set):
                self.agent_event.emit(event)
        except Exception as exc:  # noqa: BLE001 - GUI must surface and recover.
            self.error_occurred.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._busy = False
            self.finished.emit()

    def request_cancel(self) -> None:
        """Ask the in-flight turn to stop at its next safe checkpoint.

        Plain method, **not** a queued slot: the worker thread is busy inside
        `run_turn`, so this must run on the caller's (GUI) thread and only
        touch the thread-safe Event. Harmless when no turn is running — the
        flag is cleared at the start of the next `run_turn`.
        """
        self._cancel_event.set()
