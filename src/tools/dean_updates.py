"""Proactive PKU Dean's Office update surfacing.

Keeps a small local seen-state over public dean.pku.edu.cn list endpoints and
returns items that appeared since the last check. First run establishes a
baseline only, so the dashboard does not flood the user with historical data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .base import Tool, ToolResult
from .dean_resources import (
    DEFAULT_EXECUTABLE,
    DEFAULT_TIMEOUT,
    DeanNotFoundError,
    DeanTimeoutError,
    run_dean,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_STATE_PATH = _REPO_ROOT / "data" / "dean_updates_state.json"


@dataclass(frozen=True)
class DeanUpdateItem:
    key: str
    source: str
    source_label: str
    title: str
    url: str
    date: str


_SOURCES: tuple[tuple[str, str, list[str]], ...] = (
    ("rules_school", "校级规章", ["rules", "list", "--scope", "school"]),
    ("rules_national", "上级文件", ["rules", "list", "--scope", "national"]),
    ("download", "资料下载", ["download", "list"]),
    ("openinfo", "信息公开", ["openinfo", "list"]),
)


class DeanUpdatesTool(Tool):
    name: ClassVar[str] = "dean_updates"
    description: ClassVar[str] = (
        "Check public PKU Dean's Office resources and surface items that are "
        "new since the last local check. First run establishes a baseline."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of new items returned. Default: 5.",
                "minimum": 1,
                "default": 5,
            },
            "reset_baseline": {
                "type": "boolean",
                "description": "If true, replace the seen-state without surfacing updates.",
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = DEFAULT_TIMEOUT,
        state_path: str | Path = DEFAULT_STATE_PATH,
    ) -> None:
        self.executable = executable
        self.timeout = timeout
        self.state_path = Path(state_path)

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        limit = max(1, int(args.get("limit") or 5))
        reset = bool(args.get("reset_baseline", False))
        try:
            current, errors = self._fetch_current()
        except (DeanNotFoundError, DeanTimeoutError) as exc:
            return ToolResult(success=False, error=str(exc))

        if not current and errors:
            return ToolResult(success=False, error="；".join(errors))

        seen = self._load_seen()
        current_keys = {item.key for item in current}
        first_run = not self.state_path.exists()
        new_items = [] if first_run or reset else [item for item in current if item.key not in seen]
        self._save_seen(seen | current_keys)

        if first_run:
            message = f"已建立教务更新基线（{len(current)} 项）"
            status = "baseline"
        elif reset:
            message = f"已重置教务更新基线（{len(current)} 项）"
            status = "baseline"
        elif new_items:
            message = f"教务部有 {len(new_items)} 条新内容"
            status = "has_updates"
        else:
            message = "暂无教务部新内容"
            status = "ok"

        return ToolResult(
            success=True,
            data={
                "status": status,
                "message": message,
                "new_count": len(new_items),
                "updates": [asdict(item) for item in new_items[:limit]],
                "total_current": len(current),
                "baseline_only": first_run or reset,
                "errors": errors,
            },
        )

    def _fetch_current(self) -> tuple[list[DeanUpdateItem], list[str]]:
        items: list[DeanUpdateItem] = []
        errors: list[str] = []
        for source, label, cli_args in _SOURCES:
            run = run_dean(cli_args, executable=self.executable, timeout=self.timeout)
            if not run["ok"]:
                errors.append(f"{label}：{run['error']}")
                continue
            for raw in _extract_items(run.get("data")):
                normalized = _normalize_item(raw, source=source, label=label)
                if normalized is not None:
                    items.append(normalized)
        return items, errors

    def _load_seen(self) -> set[str]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        seen = data.get("seen")
        if not isinstance(seen, list):
            return set()
        return {str(item) for item in seen if item}

    def _save_seen(self, seen: set[str]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checked_at": datetime.now(_TZ).isoformat(timespec="seconds"),
            "seen": sorted(seen),
        }
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _extract_items(data: object) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("items", "list", "results", "downloads", "files"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_item(
    raw: dict[str, Any], *, source: str, label: str
) -> DeanUpdateItem | None:
    title = str(raw.get("title") or raw.get("name") or raw.get("subject") or "").strip()
    if not title:
        return None
    url = str(raw.get("url") or raw.get("href") or raw.get("link") or "").strip()
    date = str(
        raw.get("date")
        or raw.get("publish_date")
        or raw.get("published_at")
        or raw.get("time")
        or ""
    ).strip()
    raw_id = raw.get("id") or raw.get("pk") or raw.get("uuid") or url or title
    key = f"{source}:{raw_id}"
    return DeanUpdateItem(
        key=key,
        source=source,
        source_label=label,
        title=title,
        url=url,
        date=date,
    )
