"""Background refresh worker for dashboard tool data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from ..tools import ToolRegistry


class DashboardWorker(QObject):
    """Refresh selected dashboard widgets by invoking registered tools."""

    item_loaded = pyqtSignal(str, object)
    item_error = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(
        self,
        tools: ToolRegistry,
        tool_args: Mapping[str, dict[str, Any]],
        args_provider: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._tools = tools
        self._tool_args = dict(tool_args)
        self._args_provider = args_provider
        self._busy = False

    @pyqtSlot()
    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            registered = {tool.name for tool in self._tools.all()}
            for name, args in self._tool_args.items():
                if name not in registered:
                    self.item_error.emit(name, "当前模式未注册该工具")
                    continue
                merged_args = dict(args)
                if self._args_provider is not None:
                    merged_args.update(self._args_provider(name))
                result = self._tools.get(name).invoke(merged_args)
                if result.success:
                    self.item_loaded.emit(name, result.data)
                else:
                    self.item_error.emit(name, result.error or "工具调用失败")
        finally:
            self._busy = False
            self.finished.emit()
