"""Qt worker that runs Agent turns off the GUI thread.

The integration contract requires every blocking agent turn to run in a
QThread. This QObject exposes a single queued slot for user messages and
forwards AgentEvent objects back to the main window through signals.
"""

from __future__ import annotations

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

        self._busy = True
        try:
            for event in self.agent.turn(text):
                self.agent_event.emit(event)
        except Exception as exc:  # noqa: BLE001 - GUI must surface and recover.
            self.error_occurred.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._busy = False
            self.finished.emit()
