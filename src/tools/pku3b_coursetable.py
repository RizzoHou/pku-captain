"""PKU3bCourseTableTool — fetch the personal course table from the PKU portal.

Drives the vendored :mod:`pypku3b` library **in-process** (portalPublicQuery
login), then parses the portal's raw ``getCourseInfo.do`` JSON into per-day
course blocks for the dashboard. May require an OTP depending on portal policy.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from html import unescape
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_TIMEOUT,
    PKU_SECRETS_DIR,
    ClientFactory,
    Pku3bError,
    default_client_factory,
    secret_values,
    stored_credentials,
)
from .redact import redact

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
_OTP_HINT = "课表接口需要手机令牌 OTP，请在仪表盘顶部输入 OTP 后刷新。"


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
        "Fetch the student's personal course table from PKU portal. "
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
                "description": "Force a refresh instead of using cache.",
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        secrets_dir: Path | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self.secrets_dir = secrets_dir or PKU_SECRETS_DIR
        self._client_factory = client_factory or default_client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        otp_code = str(args.get("otp_code") or "").strip()
        try:
            client = self._client_factory(
                secrets_dir=self.secrets_dir,
                timeout=self.timeout,
                credentials=stored_credentials(self.secrets_dir),
            )
            table = client.get_coursetable(
                force=bool(args.get("force", False)), otp_code=otp_code
            )
        except Pku3bError as exc:
            if getattr(exc, "code", "") == "need_otp":
                return ToolResult(success=False, error=_OTP_HINT)
            message = getattr(exc, "message", str(exc))
            return ToolResult(
                success=False,
                error=redact(message, secret_values(self.secrets_dir)),
            )

        raw = table.raw if isinstance(table.raw, dict) else {}
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

    # One cell can concatenate several sessions of the SAME course (different
    # weeks / rooms). Splitting on the course marker keeps per-field extraction
    # from swallowing the next session's text into the previous one's 考试信息.
    sessions = _split_sessions(text, title)
    first = sessions[0] if sessions else text

    details: list[str] = []
    class_infos: list[str] = []
    for session in sessions:
        info = _between(session, "上课信息：", "教师：")
        if info and info not in class_infos:
            class_infos.append(info)
    if class_infos:
        details.append("上课信息：" + "；".join(class_infos))
    teacher = _after(first, "教师：")
    if teacher:
        details.append(f"教师：{teacher.split()[0]}")
    note = _between(first, "备注：", "考试信息：")
    exam = _after(first, "考试信息：")
    if exam:
        details.append(f"考试信息：{exam}")
    return title, "\n".join(details), note


def _split_sessions(text: str, title: str) -> list[str]:
    """Split a possibly multi-session course cell into per-session segments.

    Each session begins with ``<title>(主)``; the leading marker is dropped so
    each segment starts at ``上课信息：``. Falls back to the whole text when the
    marker is absent (e.g. a course name without the ``(主)`` tag)."""
    marker = f"{title}(主)"
    if marker not in text:
        return [text]
    return [part.strip() for part in text.split(marker) if part.strip()]


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
