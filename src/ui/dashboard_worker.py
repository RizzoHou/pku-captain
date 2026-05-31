"""Background refresh worker for dashboard tool data."""

from __future__ import annotations

from collections.abc import Mapping
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
    ) -> None:
        super().__init__()
        self._tools = tools
        self._tool_args = dict(tool_args)
        self._busy = False

    @pyqtSlot(dict)
    def refresh(self, dynamic_args: dict[str, dict[str, Any]] | None = None) -> None:
        """Refresh all cards. `dynamic_args` carries per-tool extras the GUI
        thread snapshotted from widgets (e.g. the OTP field) — the worker
        never reads widgets itself.
        """
        if self._busy:
            return
        self._busy = True
        dynamic_args = dynamic_args or {}
        try:
            registered = {tool.name for tool in self._tools.all()}
            for name, args in self._tool_args.items():
                if name not in registered:
                    self.item_error.emit(name, "当前模式未注册该工具")
                    continue
                merged_args = dict(args)
                merged_args.update(dynamic_args.get(name, {}))
                try:
                    result = self._tools.get(name).invoke(merged_args)
                except Exception as exc:  # noqa: BLE001 - one tool must not abort refresh
                    self.item_error.emit(name, f"工具调用异常：{exc}")
                    continue
                if result.success:
                    self.item_loaded.emit(name, result.data)
                else:
                    self.item_error.emit(name, result.error or "工具调用失败")
        finally:
            self._busy = False
            self.finished.emit()
