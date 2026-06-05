"""LectureTool — query recent PKU campus lectures.

PKU publishes lecture announcements on its media-resource platform
(https://resource.pku.edu.cn/, also reachable as lecture.pku.edu.cn).
That platform sits behind the university's unified-authentication login
and exposes no stable public JSON API, so this tool reads a curated
dataset checked into the repo at ``src/tools/data/lectures.json``. The
``Tool`` interface and ``parameters_schema`` are kept exactly as a
live-source tool would have them, so the captain can swap in a real
backend later without touching callers. See the "Implementation notes"
section of ``docs/tasks/005_lecture_tool.md``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult

_DATA_PATH = Path(__file__).resolve().parent / "data" / "lectures.json"
DEFAULT_LIMIT = 10

_FIELDS = ("title", "time", "location", "speaker", "link")


class LectureTool(Tool):
    name: ClassVar[str] = "lecture"
    description: ClassVar[str] = (
        "List recent / upcoming PKU campus lectures (title, time, location, "
        "speaker, link). Optionally filter by `keyword`, a `start_date` / "
        "`end_date` range, and cap the count with `limit` (default 10). When "
        "the user asks for the total count or for ALL lectures, pass a large "
        "`limit` (e.g. 1000) so the result is not silently truncated at the "
        "default. Data source: a curated snapshot of PKU's lecture "
        "announcement platform."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": f"Max lectures to return (default {DEFAULT_LIMIT}).",
            },
            "keyword": {
                "type": "string",
                "description": (
                    "Case-insensitive substring matched against the title, "
                    "speaker, and location."
                ),
            },
            "start_date": {
                "type": "string",
                "description": "Only lectures on or after this date (YYYY-MM-DD).",
            },
            "end_date": {
                "type": "string",
                "description": "Only lectures on or before this date (YYYY-MM-DD).",
            },
        },
        "additionalProperties": False,
    }

    def __init__(self, data_path: Path = _DATA_PATH) -> None:
        self.data_path = data_path

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        keyword = (args.get("keyword") or "").strip().lower()
        try:
            start = _parse_date(args.get("start_date"))
            end = _parse_date(args.get("end_date"))
        except ValueError as exc:
            return ToolResult(success=False, error=f"日期格式无效：{exc}")

        try:
            raw = self.data_path.read_text(encoding="utf-8")
            records = json.loads(raw)
        except FileNotFoundError:
            return ToolResult(
                success=False, error=f"讲座数据文件缺失：{self.data_path}"
            )
        except (OSError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=f"讲座数据读取失败：{exc}")

        if not isinstance(records, list):
            return ToolResult(success=False, error="讲座数据格式错误：期望 JSON 数组")

        lectures = [_normalize(r) for r in records if isinstance(r, dict)]

        if keyword:
            lectures = [
                lec
                for lec in lectures
                if keyword in (lec["title"] + lec["speaker"] + lec["location"]).lower()
            ]
        if start is not None or end is not None:
            lectures = [lec for lec in lectures if _in_range(lec, start, end)]

        lectures.sort(key=lambda lec: lec["time"] or "")
        lectures = lectures[: _resolve_limit(args.get("limit"))]

        return ToolResult(success=True, data=lectures)


def _resolve_limit(value: Any) -> int:
    """Coerce the `limit` argument; fall back to the default on bad input."""
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return limit if limit > 0 else DEFAULT_LIMIT


def _parse_date(value: Any) -> date | None:
    """Parse a YYYY-MM-DD filter argument; ``None``/empty means no filter."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return date.fromisoformat(str(value).strip())


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Project a raw record onto the five guaranteed fields."""
    return {field: record.get(field) or "" for field in _FIELDS}


def _in_range(lecture: dict[str, Any], start: date | None, end: date | None) -> bool:
    """Whether a lecture's date falls within an inclusive [start, end] range."""
    raw = lecture.get("time") or ""
    try:
        when = datetime.fromisoformat(raw).date()
    except ValueError:
        return False
    if start is not None and when < start:
        return False
    if end is not None and when > end:
        return False
    return True
