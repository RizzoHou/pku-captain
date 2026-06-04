"""Background refresh worker for dashboard tool data."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    @pyqtSlot(dict, list)
    def refresh(
        self,
        dynamic_args: dict[str, dict[str, Any]] | None = None,
        keys: list[str] | None = None,
    ) -> None:
        """Refresh dashboard cards by invoking registered tools concurrently.

        `dynamic_args` carries per-tool extras the GUI thread snapshotted from
        widgets (e.g. the OTP field) — the worker never reads widgets itself.
        `keys` scopes the refresh to those tools; an empty/None list refreshes
        all, so a single card's refresh button only reloads its own data and
        does not fan out into a full-dashboard reload.

        The selected tools run in parallel on a thread pool — each
        ``invoke()`` blocks on a subprocess (pku3b/plib) or the network
        (treehole), so concurrency cuts total refresh time from the sum of the
        cards to the slowest single card. Each card's ``item_loaded`` /
        ``item_error`` is emitted from this thread as that tool finishes, so the
        cross-thread signal delivery and the GUI wiring are unchanged. The tools
        touch disjoint resources, so this is safe; the one shared resource is
        pku3b's content-addressed cache — on a cold/stale session
        ``pku3b_assignments`` and ``pku3b_announcements`` share the
        ``Blackboard::_get_courses`` cache key and may both fetch + re-login,
        which self-heals to at most a redundant fetch (verified against the
        pku3b fork source).
        """
        if self._busy:
            return
        self._busy = True
        dynamic_args = dynamic_args or {}
        selected = set(keys or ())
        try:
            registered = {tool.name for tool in self._tools.all()}
            jobs: list[tuple[str, dict[str, Any]]] = []
            for name, args in self._tool_args.items():
                if selected and name not in selected:
                    continue
                if name not in registered:
                    self.item_error.emit(name, "当前模式未注册该工具")
                    continue
                merged_args = dict(args)
                merged_args.update(dynamic_args.get(name, {}))
                jobs.append((name, merged_args))

            if not jobs:
                return

            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                futures = {
                    pool.submit(self._invoke, name, call_args): name
                    for name, call_args in jobs
                }
                for future in as_completed(futures):
                    name = futures[future]
                    ok, payload = future.result()
                    if ok:
                        self.item_loaded.emit(name, payload)
                    else:
                        self.item_error.emit(name, payload)
        finally:
            self._busy = False
            self.finished.emit()

    def _invoke(self, name: str, args: dict[str, Any]) -> tuple[bool, Any]:
        """Invoke one tool off-thread. Returns ``(ok, data_or_error)`` and never
        raises, so one failing tool cannot abort the whole refresh."""
        try:
            result = self._tools.get(name).invoke(args)
        except Exception as exc:  # noqa: BLE001 - one tool must not abort refresh
            return False, f"工具调用异常：{exc}"
        if result.success:
            return True, result.data
        return False, result.error or "工具调用失败"
