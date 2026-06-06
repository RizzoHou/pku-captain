"""MorningBriefingWorkflow — compose tools into a daily morning briefing.

Aggregates today's assignment deadlines and recent course announcements into
one human-readable briefing. Part of core feature #4 (multi-step workflows);
extends the single-tool `HelloWorkflow` shape into multi-tool orchestration.

Graceful degradation is a hard requirement: each section is independent.
A tool that is not registered (e.g. `pku3b_*` in offline mode) or whose
`invoke()` fails is noted in the briefing and skipped — the workflow reports
`success=False` only when no data source is reachable at all.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from ..tools.base import ToolResult
from .base import Workflow, WorkflowResult

_MAX_ANNOUNCEMENTS = 5


class MorningBriefingWorkflow(Workflow):
    name: ClassVar[str] = "morning_briefing"
    description: ClassVar[str] = (
        "Compose a morning briefing: today's assignment deadlines and recent "
        "course announcements."
    )

    def run(self, args: dict[str, Any] | None = None) -> WorkflowResult:
        today = self._today()

        details: dict[str, Any] = {}
        sections: list[str] = []
        # Count the real data sources (clock is only the date source).
        reachable = 0

        reachable += self._assignments_section(today, details, sections)
        reachable += self._announcements_section(details, sections)

        summary = f"早安！今天是 {today.isoformat()}。\n\n" + "\n\n".join(sections)

        if reachable == 0:
            return WorkflowResult(
                success=False,
                summary=summary,
                details=details,
                error="no data source reachable for the morning briefing",
            )
        return WorkflowResult(success=True, summary=summary, details=details)

    # -- sections ------------------------------------------------------
    #
    # Each `_*_section` appends exactly one block to `sections` (so the
    # summary always carries every section, available or not) and returns
    # 1 if its data source produced usable data, else 0.

    def _assignments_section(
        self, today: date, details: dict[str, Any], sections: list[str]
    ) -> int:
        result = self._invoke("pku3b_assignments", {})
        if result is None:
            sections.append("【今日截止】当前不可用（offline 模式未注册 pku3b_assignments 工具）")
            return 0
        if not result.success:
            sections.append(f"【今日截止】获取失败：{result.error}")
            return 0
        details["pku3b_assignments"] = result.data
        items = result.data.get("assignments", []) if isinstance(result.data, dict) else []
        due_today = [
            a
            for a in items
            if not a.get("completed") and _falls_on(a.get("deadline_iso"), today)
        ]
        if due_today:
            lines = "\n".join(
                "  - {course}：{title}（{deadline}）".format(
                    course=a.get("course_name", ""),
                    title=a.get("title", ""),
                    deadline=a.get("deadline_raw") or a.get("deadline_iso") or "时间未知",
                )
                for a in due_today
            )
            sections.append(f"【今日截止】共 {len(due_today)} 项\n{lines}")
        else:
            outstanding = sum(1 for a in items if not a.get("completed"))
            sections.append(
                f"【今日截止】今天没有作业截止（仍有 {outstanding} 项未完成作业）"
            )
        return 1

    def _announcements_section(
        self, details: dict[str, Any], sections: list[str]
    ) -> int:
        result = self._invoke("pku3b_announcements", {"limit": _MAX_ANNOUNCEMENTS})
        if result is None:
            sections.append("【课程公告】当前不可用（offline 模式未注册 pku3b_announcements 工具）")
            return 0
        if not result.success:
            sections.append(f"【课程公告】获取失败：{result.error}")
            return 0
        details["pku3b_announcements"] = result.data
        items = (
            result.data.get("announcements", []) if isinstance(result.data, dict) else []
        )
        if items:
            lines = "\n".join(
                "  - {course}：{title}".format(
                    course=a.get("course", ""), title=a.get("title", "")
                )
                for a in items
            )
            sections.append(f"【课程公告】最近 {len(items)} 条\n{lines}")
        else:
            sections.append("【课程公告】暂无公告")
        return 1

    # -- helpers -------------------------------------------------------

    def _invoke(self, name: str, args: dict[str, Any]) -> ToolResult | None:
        """Invoke a tool by name, or return ``None`` if it is not registered.

        A tool that raises is degraded into a failed ``ToolResult`` rather
        than propagating — one broken tool must not abort the briefing.
        """
        if not any(t.name == name for t in self.tools.all()):
            return None
        try:
            return self.tools.get(name).invoke(args)
        except Exception as exc:  # noqa: BLE001 - degrade, never abort
            return ToolResult(success=False, error=f"{name} 调用异常：{exc}")

    def _today(self) -> date:
        """Resolve today's date via the ``clock`` tool, else the system clock."""
        result = self._invoke("clock", {})
        if result is not None and result.success and isinstance(result.data, str):
            try:
                return datetime.fromisoformat(result.data).date()
            except ValueError:
                pass
        return datetime.now().astimezone().date()


def _falls_on(iso: Any, day: date) -> bool:
    """Whether an ISO-8601 datetime/date string falls on ``day``."""
    if not isinstance(iso, str) or not iso:
        return False
    try:
        return datetime.fromisoformat(iso).date() == day
    except ValueError:
        return False
