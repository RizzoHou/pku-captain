"""PKU3bCourseTableTool — fetch the personal course table via pku3b."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_EXECUTABLE,
    DEFAULT_TIMEOUT,
    Pku3bNotFoundError,
    Pku3bTimeoutError,
    run_pku3b,
)

_DAYS = [
    ("mon", "周一"),
    ("tue", "周二"),
    ("wed", "周三"),
    ("thu", "周四"),
    ("fri", "周五"),
    ("sat", "周六"),
    ("sun", "周日"),
]
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class CourseBlock:
    day_key: str
    day_name: str
    start_slot: int
    end_slot: int
    title: str
    detail: str
    note: str


class PKU3bCourseTableTool(Tool):
    name: ClassVar[str] = "pku3b_coursetable"
    description: ClassVar[str] = (
        "Fetch the student's personal course table from PKU portal via pku3b. "
        "May require an OTP code depending on portal login policy."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "otp_code": {
                "type": "string",
                "description": "Optional PKU portal phone-token OTP code.",
            },
            "force": {
                "type": "boolean",
                "description": "Force pku3b to refresh instead of using cache.",
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.executable = executable
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        cli_args = ["coursetable", "--raw"]
        if bool(args.get("force", False)):
            cli_args.append("--force")
        otp_code = str(args.get("otp_code") or "").strip()
        if otp_code:
            cli_args.extend(["--otp-code", otp_code])

        try:
            run = run_pku3b(cli_args, executable=self.executable, timeout=self.timeout)
        except Pku3bNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))
        except Pku3bTimeoutError as exc:
            return ToolResult(success=False, error=str(exc))

        if not run.ok:
            err = run.stderr.strip() or run.stdout.strip() or "unknown error"
            if "input device is not a TTY" in err:
                err = "课表接口需要手机令牌 OTP，请在仪表盘顶部输入 OTP 后刷新。"
            return ToolResult(success=False, error=f"pku3b exited {run.returncode}: {err}")

        try:
            raw = json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            return ToolResult(success=False, error=f"failed to parse course table JSON: {exc}")

        blocks = _parse_course_table(raw)
        return ToolResult(
            success=True,
            data={
                "days": [{"key": key, "name": name} for key, name in _DAYS],
                "blocks": [asdict(block) for block in blocks],
                "raw": raw,
            },
        )


def _parse_course_table(raw: dict[str, Any]) -> list[CourseBlock]:
    slots = raw.get("course")
    if not isinstance(slots, list):
        return []

    blocks: list[CourseBlock] = []
    for day_key, day_name in _DAYS:
        day_slots: list[tuple[int, str, str, str]] = []
        for index, slot in enumerate(slots, start=1):
            if not isinstance(slot, dict):
                continue
            course = slot.get(day_key)
            if not isinstance(course, dict):
                continue
            name = course.get("courseName")
            if not isinstance(name, str) or not name.strip():
                continue
            title, detail, note = _clean_course_info(name)
            day_slots.append((index, title, detail, note))

        i = 0
        while i < len(day_slots):
            start, title, detail, note = day_slots[i]
            end = start
            j = i + 1
            while j < len(day_slots) and day_slots[j][1:] == (title, detail, note):
                end = day_slots[j][0]
                j += 1
            blocks.append(
                CourseBlock(
                    day_key=day_key,
                    day_name=day_name,
                    start_slot=start,
                    end_slot=end,
                    title=title,
                    detail=detail,
                    note=note,
                )
            )
            i = j
    return blocks


def _clean_course_info(value: str) -> tuple[str, str, str]:
    text = unescape(_TAG_RE.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    title = text.split("(主)", 1)[0].strip() or text

    details: list[str] = []
    class_info = _between(text, "上课信息：", "教师：")
    if class_info:
        details.append(class_info)
    teacher = _after(text, "教师：")
    if teacher:
        details.append(f"教师：{teacher.split()[0]}")
    note = _between(text, "备注：", "考试信息：")
    exam = _after(text, "考试信息：")
    if exam:
        details.append(f"考试：{exam}")
    return title, " | ".join(details), note


def _between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    rest = text[start_index + len(start):]
    end_index = rest.find(end)
    return rest[:end_index if end_index >= 0 else len(rest)].strip()


def _after(text: str, marker: str) -> str:
    index = text.find(marker)
    if index < 0:
        return ""
    return text[index + len(marker):].strip()
