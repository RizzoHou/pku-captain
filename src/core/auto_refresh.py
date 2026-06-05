"""Auto-refresh settings, change detection, and notification digests."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..llm.base import ChatMessage, LLMProvider

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS_PATH = _REPO_ROOT / "data" / "auto_refresh_settings.json"
DEFAULT_AUTO_REFRESH_INTERVAL = 300
MIN_AUTO_REFRESH_INTERVAL = 60
MAX_NOTIFICATION_BODY = 240


@dataclass(frozen=True)
class AutoRefreshSettings:
    enabled: bool = True
    interval_seconds: int = DEFAULT_AUTO_REFRESH_INTERVAL
    notify_enabled: bool = True


class AutoRefreshSettingsStore:
    """Persist user preferences for dashboard auto-refresh."""

    def __init__(self, path: Path | str = _DEFAULT_SETTINGS_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> AutoRefreshSettings:
        with self._lock:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return AutoRefreshSettings()
        if not isinstance(data, dict):
            return AutoRefreshSettings()
        return AutoRefreshSettings(
            enabled=bool(data.get("enabled", True)),
            interval_seconds=_normalize_interval(data.get("interval_seconds")),
            notify_enabled=bool(data.get("notify_enabled", True)),
        )

    def save(self, settings: AutoRefreshSettings) -> None:
        normalized = AutoRefreshSettings(
            enabled=bool(settings.enabled),
            interval_seconds=_normalize_interval(settings.interval_seconds),
            notify_enabled=bool(settings.notify_enabled),
        )
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(asdict(normalized), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


@dataclass(frozen=True)
class DashboardChange:
    source: str
    kind: str
    title: str
    detail: str = ""


def detect_dashboard_changes(
    key: str, previous: object, current: object
) -> list[DashboardChange]:
    """Return user-facing changes between two dashboard payloads."""
    if key == "pku3b_assignments":
        return _assignment_changes(previous, current)
    if key == "pku3b_announcements":
        return _list_added_changes(
            source="课程通知",
            kind="新增",
            previous_items=_items(previous, "announcements"),
            current_items=_items(current, "announcements"),
            id_fields=("id", "course", "title"),
            title_fn=lambda item: str(item.get("title") or "未命名通知"),
            detail_fn=lambda item: str(item.get("course") or "未知课程"),
        )
    if key == "dean_updates":
        return _list_added_changes(
            source="教务通知",
            kind="新增",
            previous_items=_items(previous, "updates"),
            current_items=_items(current, "updates"),
            id_fields=("url", "title", "date"),
            title_fn=lambda item: str(item.get("title") or "未命名通知"),
            detail_fn=lambda item: str(
                item.get("source_label") or item.get("date") or ""
            ),
        )
    if key == "lecture":
        return _list_added_changes(
            source="讲座推荐",
            kind="新增",
            previous_items=previous if isinstance(previous, list) else [],
            current_items=current if isinstance(current, list) else [],
            id_fields=("url", "title", "time"),
            title_fn=lambda item: str(item.get("title") or "未命名讲座"),
            detail_fn=lambda item: str(item.get("time") or item.get("location") or ""),
        )
    if key == "treehole_updates":
        return _treehole_changes(previous, current)
    return []


class DashboardDigest:
    """Turn structured changes into a short Chinese notification body."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    def summarize(self, changes: list[DashboardChange]) -> str:
        if not changes:
            return ""
        fallback = _fallback_digest(changes)
        if self._llm is None:
            return fallback
        prompt = (
            "请把下面这些 PKU Captain 后台刷新检测到的变化整理成简短中文通知。"
            "要求：最多 4 条，突出用户需要行动的信息，不要编造，不要寒暄，"
            "总长度控制在 220 字内。\n\n"
            + "\n".join(
                f"- [{c.source}][{c.kind}] {c.title} {c.detail}".strip()
                for c in changes[:12]
            )
        )
        try:
            response = self._llm.chat([ChatMessage(role="user", content=prompt)])
        except Exception:  # noqa: BLE001 - notification must degrade cleanly
            return fallback
        text = response.text.strip()
        return _clip(text, MAX_NOTIFICATION_BODY) if text else fallback


class MacOSNotifier:
    """Send a short native macOS notification via osascript."""

    def __init__(
        self,
        *,
        runner: Any | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._runner = runner if runner is not None else subprocess.run
        self._platform = platform_name if platform_name is not None else sys.platform

    def notify(
        self,
        body: str,
        *,
        title: str = "PKU Captain",
        subtitle: str = "发现新变化",
    ) -> dict[str, object]:
        if self._platform != "darwin":
            return {"ok": False, "message": "系统通知仅支持 macOS"}
        text = _clip(body.strip(), MAX_NOTIFICATION_BODY)
        if not text:
            return {"ok": False, "message": "通知内容为空"}
        script = """
on run argv
  display notification (item 3 of argv) with title (item 1 of argv) subtitle (item 2 of argv)
end run
""".strip()
        result = self._runner(
            ["osascript", "-", title, subtitle, text],
            check=False,
            input=script,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "通知已发送"}
        detail = (getattr(result, "stderr", "") or "").strip()
        return {"ok": False, "message": detail or f"osascript 退出码 {result.returncode}"}


def _assignment_changes(previous: object, current: object) -> list[DashboardChange]:
    old = {
        _identity(item, ("id", "course_id", "title")): item
        for item in _items(previous, "assignments")
    }
    changes: list[DashboardChange] = []
    for item in _items(current, "assignments"):
        ident = _identity(item, ("id", "course_id", "title"))
        title = str(item.get("title") or "未命名作业")
        course = str(item.get("course_name") or item.get("course_title") or "未知课程")
        deadline = str(item.get("deadline_raw") or item.get("deadline_iso") or "时间未知")
        if ident not in old:
            changes.append(
                DashboardChange(
                    source="近期 DDL",
                    kind="新增",
                    title=title,
                    detail=f"{course}，截止：{deadline}",
                )
            )
            continue
        old_item = old[ident]
        if old_item.get("deadline_iso") != item.get("deadline_iso"):
            changes.append(
                DashboardChange(
                    source="近期 DDL",
                    kind="截止时间变化",
                    title=title,
                    detail=f"{course}，新截止：{deadline}",
                )
            )
        if bool(old_item.get("completed")) != bool(item.get("completed")):
            state = "已完成" if item.get("completed") else "未完成"
            changes.append(
                DashboardChange(
                    source="近期 DDL",
                    kind="状态变化",
                    title=title,
                    detail=f"{course}，当前：{state}",
                )
            )
    return changes


def _treehole_changes(previous: object, current: object) -> list[DashboardChange]:
    old_count = _int_field(previous, "unread_count")
    new_count = _int_field(current, "unread_count")
    if new_count <= old_count:
        return []
    return [
        DashboardChange(
            source="树洞消息",
            kind="新增回复",
            title=f"新增 {new_count - old_count} 条未读回复",
            detail=f"当前未读 {new_count} 条",
        )
    ]


def _list_added_changes(
    *,
    source: str,
    kind: str,
    previous_items: object,
    current_items: object,
    id_fields: tuple[str, ...],
    title_fn: Any,
    detail_fn: Any,
) -> list[DashboardChange]:
    old_ids = {
        _identity(item, id_fields)
        for item in previous_items
        if isinstance(item, dict)
    }
    changes: list[DashboardChange] = []
    for item in current_items:
        if not isinstance(item, dict):
            continue
        ident = _identity(item, id_fields)
        if ident in old_ids:
            continue
        changes.append(
            DashboardChange(
                source=source,
                kind=kind,
                title=title_fn(item),
                detail=detail_fn(item),
            )
        )
    return changes


def _items(payload: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    values = payload.get(field)
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _identity(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts = [str(item.get(field) or "") for field in fields]
    raw = "|".join(parts) if any(parts) else json.dumps(item, sort_keys=True, default=str)
    return re.sub(r"\s+", "", raw).casefold()


def _int_field(payload: object, field: str) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def _fallback_digest(changes: list[DashboardChange]) -> str:
    lines = [f"Captain 发现 {len(changes)} 条新变化："]
    for index, change in enumerate(changes[:4], start=1):
        detail = f"（{change.detail}）" if change.detail else ""
        lines.append(f"{index}. {change.source}：{change.kind}「{change.title}」{detail}")
    remaining = len(changes) - 4
    if remaining > 0:
        lines.append(f"另有 {remaining} 条变化，请打开 PKU Captain 查看。")
    return _clip("\n".join(lines), MAX_NOTIFICATION_BODY)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _normalize_interval(value: object) -> int:
    try:
        seconds = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_AUTO_REFRESH_INTERVAL
    return max(MIN_AUTO_REFRESH_INTERVAL, seconds)
