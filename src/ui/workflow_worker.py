"""Background worker for running registered workflows from the GUI."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..workflows import WorkflowRegistry, WorkflowResult


class WorkflowWorker(QObject):
    """Run workflows outside the GUI thread and report their result."""

    started = pyqtSignal(str)
    finished = pyqtSignal(str, object)
    error_occurred = pyqtSignal(str, str)

    def __init__(self, workflows: WorkflowRegistry) -> None:
        super().__init__()
        self._workflows = workflows
        self._busy = False

    @pyqtSlot(str, dict)
    def run_workflow(self, name: str, args: dict[str, Any]) -> None:
        if self._busy:
            self.error_occurred.emit(name, "已有工作流正在运行")
            return

        self._busy = True
        self.started.emit(name)
        try:
            result = self._workflows.get(name).run(args)
        except KeyError:
            self.error_occurred.emit(name, f"未注册工作流：{name}")
        except Exception as exc:  # noqa: BLE001 - GUI should display and recover.
            self.error_occurred.emit(name, f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(name, result)
        finally:
            self._busy = False


def workflow_summary(result: WorkflowResult) -> str:
    """Return the user-visible summary for a workflow result."""
    if result.success:
        return result.summary
    if result.error:
        return f"{result.summary}\n\n工作流未完全成功：{result.error}"
    return result.summary
