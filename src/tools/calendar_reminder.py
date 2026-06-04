"""CalendarReminderTool — push DDLs into macOS Calendar.app as alarmed events.

Part of the core feature #3 tool set, and the notification path the
storage-only `ReminderTool` deliberately leaves out. Each selected
assignment deadline becomes a Calendar event with a ``display alarm`` so
macOS fires a native notification ahead of the due time.

Events go into a dedicated ``PKU Captain`` calendar (created on first use)
rather than the user's real calendars: it isolates the app's writes, makes
cleanup a one-click calendar delete, and keeps re-adds from polluting
existing calendars. The calendar still shows in Calendar's unified view.

macOS-only: it shells to ``osascript``. On any other platform `invoke`
returns a graceful failure instead of raising. The first run also triggers
the one-time macOS Automation (TCC) permission prompt; if it is denied the
tool surfaces an actionable message instead of a raw AppleScript dump.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .base import Tool, ToolResult

_TZ = ZoneInfo("Asia/Shanghai")
_DEFAULT_CALENDAR = "PKU Captain"
_DEFAULT_ALARM_MINUTES = 1440  # one day before the deadline
_OSASCRIPT_TIMEOUT = 30.0
_PERMISSION_MESSAGE = (
    "未获得控制『日历』的权限。请在 系统设置 → 隐私与安全性 → 自动化 中，"
    "允许本程序（或终端）控制『日历』后重试。"
)

# AppleScript run with `osascript - <argv...>`: the script reads from stdin
# and receives the event fields as argv, so titles/notes with quotes or CJK
# never need shell/string escaping. The date is built from numeric components
# (locale-independent); `day` is set to 1 first so changing the month can't
# overflow off a 29-31 day boundary.
_ADD_EVENT_APPLESCRIPT = """
on run argv
    set cn to item 1 of argv
    set t to item 2 of argv
    set yr to (item 3 of argv) as integer
    set mo to (item 4 of argv) as integer
    set dy to (item 5 of argv) as integer
    set hr to (item 6 of argv) as integer
    set mn to (item 7 of argv) as integer
    set am to (item 8 of argv) as integer
    set nt to item 9 of argv

    set d1 to current date
    set day of d1 to 1
    set year of d1 to yr
    set month of d1 to mo
    set day of d1 to dy
    set hours of d1 to hr
    set minutes of d1 to mn
    set seconds of d1 to 0
    set d2 to d1 + (30 * minutes)
    set negAlarm to 0 - am

    tell application "Calendar"
        if not (exists calendar cn) then
            make new calendar with properties {name:cn}
        end if
        tell calendar cn
            set ev to make new event with properties {summary:t, start date:d1, end date:d2}
            set description of ev to nt
            tell ev
                set newAlarm to make new display alarm at end of display alarms
                set trigger interval of newAlarm to negAlarm
            end tell
        end tell
    end tell
    return "ok"
end run
"""


@dataclass
class _Parsed:
    """A validated item ready to hand to AppleScript."""

    title: str
    when: datetime  # in local time, for Calendar
    notes: str


class CalendarReminderTool(Tool):
    name: ClassVar[str] = "calendar_reminder"
    description: ClassVar[str] = (
        "Add assignment DDLs to the macOS Calendar app as events with a "
        "notification alarm, so the user gets a native macOS reminder before "
        "each deadline. Events go into a dedicated 'PKU Captain' calendar. "
        "Pass `items`, a list of {title, deadline_iso, notes?}; each "
        "`deadline_iso` is an ISO-8601 datetime (e.g. '2026-06-06T23:59:00'). "
        "Optional `alarm_minutes_before` sets how long before the deadline the "
        "alarm fires (default 1440 = one day). macOS only."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Deadlines to add as alarmed calendar events.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Event title, e.g. the assignment name.",
                        },
                        "deadline_iso": {
                            "type": "string",
                            "description": (
                                "Deadline as an ISO-8601 datetime, e.g. "
                                "'2026-06-06T23:59:00'."
                            ),
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional event notes / description.",
                        },
                    },
                    "required": ["title", "deadline_iso"],
                    "additionalProperties": False,
                },
            },
            "calendar_name": {
                "type": "string",
                "description": "Target calendar (created if missing). Default 'PKU Captain'.",
            },
            "alarm_minutes_before": {
                "type": "integer",
                "description": (
                    "Minutes before the deadline to fire the alarm. Default 1440 "
                    "(one day). Use 0 to alarm at the deadline."
                ),
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    def __init__(self, timeout: float = _OSASCRIPT_TIMEOUT) -> None:
        self._timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        if sys.platform != "darwin":
            return ToolResult(
                success=False,
                error="日历提醒仅支持 macOS（需要 osascript 调用『日历』App）。",
            )

        raw_items = args.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return ToolResult(success=False, error="`items` 不能为空。")

        calendar_name = (args.get("calendar_name") or _DEFAULT_CALENDAR).strip()
        calendar_name = calendar_name or _DEFAULT_CALENDAR
        alarm_minutes = _coerce_alarm(args.get("alarm_minutes_before"))

        added: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for raw in raw_items:
            title = str((raw or {}).get("title") or "").strip() if isinstance(raw, dict) else ""
            try:
                parsed = _parse_item(raw)
            except ValueError as exc:
                failed.append({"title": title or "(未命名)", "reason": str(exc)})
                continue

            error = self._add_event(parsed, calendar_name, alarm_minutes)
            if error is None:
                added.append(
                    {"title": parsed.title, "when": parsed.when.strftime("%Y-%m-%d %H:%M")}
                )
            else:
                failed.append({"title": parsed.title, "reason": error})
                # A permission denial fails every subsequent item identically;
                # stop hammering osascript and report what we know.
                if error == _PERMISSION_MESSAGE:
                    for remaining in raw_items[len(added) + len(failed):]:
                        name = (
                            str((remaining or {}).get("title") or "(未命名)").strip()
                            if isinstance(remaining, dict)
                            else "(未命名)"
                        )
                        failed.append({"title": name or "(未命名)", "reason": error})
                    break

        return ToolResult(
            success=bool(added),
            data={
                "calendar": calendar_name,
                "alarm_minutes_before": alarm_minutes,
                "added": added,
                "failed": failed,
            },
            error=None if added else _summarize_failure(failed),
        )

    def _add_event(self, item: _Parsed, calendar_name: str, alarm_minutes: int) -> str | None:
        """Run the AppleScript for one event; return None on success or an error string."""
        argv = [
            "osascript",
            "-",
            calendar_name,
            item.title,
            str(item.when.year),
            str(item.when.month),
            str(item.when.day),
            str(item.when.hour),
            str(item.when.minute),
            str(alarm_minutes),
            item.notes,
        ]
        try:
            proc = subprocess.run(
                argv,
                input=_ADD_EVENT_APPLESCRIPT,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "调用『日历』超时。"
        except FileNotFoundError:
            return "未找到 osascript，无法调用 macOS『日历』。"

        if proc.returncode == 0:
            return None
        stderr = (proc.stderr or "").strip()
        if _is_not_authorized(stderr):
            return _PERMISSION_MESSAGE
        return stderr or f"osascript 退出码 {proc.returncode}。"


def _parse_item(raw: object) -> _Parsed:
    if not isinstance(raw, dict):
        raise ValueError("条目格式不正确。")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("缺少标题。")
    deadline_iso = str(raw.get("deadline_iso") or "").strip()
    if not deadline_iso:
        raise ValueError("缺少截止时间（deadline_iso）。")
    when = _parse_local(deadline_iso)
    if when is None:
        raise ValueError(f"无法解析截止时间：{deadline_iso}")
    notes = str(raw.get("notes") or "")
    return _Parsed(title=title, when=when, notes=notes)


def _parse_local(value: str) -> datetime | None:
    """Parse an ISO-8601 deadline into local time for Calendar.

    Naive timestamps are assumed Asia/Shanghai (matching ReminderTool); any
    timestamp is then converted to the machine's local zone, since Calendar
    interprets the components we hand it as local wall-clock time.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_TZ)
    return parsed.astimezone()


def _coerce_alarm(value: object) -> int:
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        return _DEFAULT_ALARM_MINUTES
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return max(0, int(value))
    return _DEFAULT_ALARM_MINUTES


def _is_not_authorized(message: str) -> bool:
    lowered = message.lower()
    return "-1743" in message or "not authorized" in lowered


def _summarize_failure(failed: list[dict[str, str]]) -> str:
    if not failed:
        return "未添加任何日历提醒。"
    reasons = {entry.get("reason", "") for entry in failed}
    if len(reasons) == 1:
        return next(iter(reasons)) or "未添加任何日历提醒。"
    return "；".join(f"{e.get('title')}：{e.get('reason')}" for e in failed)
