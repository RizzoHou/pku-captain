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

from dean import resources

from .base import Tool, ToolResult
from .dean_resources import DEFAULT_TIMEOUT, ClientFactory, fetch_dean

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
    # Raw site id (notice/rule ids are ints), kept so the GUI can fetch the
    # full text via `notice_show` / `rules_show` without re-parsing ``key``.
    item_id: str = ""


# Each source is a first-page list fetch against the vendored ``dean`` library.
# ``fetch_dean`` runs the call in-process and returns the same ``{ok, data}``
# envelope the old subprocess wrapper produced, so item extraction is unchanged.
_SOURCES: tuple[tuple[str, str, Any], ...] = (
    ("rules_school", "校级规章", lambda c: resources.list_rules(c, "school")),
    ("rules_national", "上级文件", lambda c: resources.list_rules(c, "national")),
    ("notice", "通知公告", lambda c: resources.list_notices(c)),
    ("download", "资料下载", lambda c: resources.list_files(c, "download")),
    ("openinfo", "信息公开", lambda c: resources.list_files(c, "openinfo")),
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
        timeout: float = DEFAULT_TIMEOUT,
        state_path: str | Path = DEFAULT_STATE_PATH,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self.state_path = Path(state_path)
        self._client_factory = client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        limit = max(1, int(args.get("limit") or 5))
        reset = bool(args.get("reset_baseline", False))
        current, errors = self._fetch_current()

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
                # Full current snapshot of every source's first page. The GUI
                # accumulates this into a never-lossy inbox and renders by
                # recency window; `updates`/`new_count` above stay for the
                # agent's "what's new" answer (a separate notion of "new").
                "items": [asdict(item) for item in current],
                "total_current": len(current),
                "baseline_only": first_run or reset,
                "errors": errors,
            },
        )

    def _fetch_current(self) -> tuple[list[DeanUpdateItem], list[str]]:
        items: list[DeanUpdateItem] = []
        errors: list[str] = []
        for source, label, fetch_call in _SOURCES:
            run = fetch_dean(
                fetch_call, timeout=self.timeout, client_factory=self._client_factory
            )
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
    # download / openinfo items expose the link as ``download_url`` rather than
    # ``url``, so include it in the fallback chain to keep those rows openable.
    url = str(
        raw.get("url")
        or raw.get("href")
        or raw.get("link")
        or raw.get("download_url")
        or ""
    ).strip()
    date = str(
        raw.get("date")
        or raw.get("publish_date")
        or raw.get("published_at")
        or raw.get("time")
        or ""
    ).strip()
    item_id = str(raw.get("id") or raw.get("pk") or "").strip()
    raw_id = raw.get("id") or raw.get("pk") or raw.get("uuid") or url or title
    key = f"{source}:{raw_id}"
    return DeanUpdateItem(
        key=key,
        source=source,
        source_label=label,
        title=title,
        url=url,
        date=date,
        item_id=item_id,
    )


def merge_dean_updates(
    existing: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    now: str,
) -> list[dict[str, Any]]:
    """Accumulate dean items by ``key`` so the dashboard never loses content.

    Each poll returns the current first-page snapshot per source; merging rather
    than replacing keeps every item ever seen — the card renders a recency
    window and the rest moves to history, with nothing dropped (this resolves
    the old "replaces-not-accumulates → item vanishes on the next poll" limit).
    ``first_seen`` is stamped once (the earliest observation wins) and drives
    windowing for date-less sources (rules); the mutable fields
    (``title``/``url``/``date``/``source_label``/``item_id``) track the latest
    snapshot. ``now`` is the ISO timestamp stamped on brand-new items (passed in
    so this stays pure / deterministic). Order-independent across a batch and
    idempotent on re-merging an already-accumulated list.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _absorb(entry: dict[str, Any]) -> None:
        key = str(entry.get("key") or "").strip()
        if not key:
            return
        incoming_first = entry.get("first_seen")
        cur = merged.get(key)
        if cur is None:
            cur = dict(entry)
            cur["first_seen"] = str(incoming_first or now)
            merged[key] = cur
            order.append(key)
            return
        preserved = cur.get("first_seen")
        cur.update({k: v for k, v in entry.items() if k != "first_seen"})
        candidates = [str(t) for t in (preserved, incoming_first) if t]
        cur["first_seen"] = min(candidates) if candidates else now

    for entry in list(existing or []) + list(new_items or []):
        if isinstance(entry, dict):
            _absorb(entry)
    return [merged[key] for key in order]


class DeanInboxStore:
    """Persisted, never-lossy accumulator of dean items feeding the dashboard.

    Mirrors ``TreeholeInboxStore``: each poll's snapshot is merged in (union by
    ``key``) and persisted to ``data/dean_inbox.json``, so an item stays cached
    across restarts and is never dropped — the card shows a recency window and
    the dialog exposes the full 近期 + 历史 archive. Unlike the treehole inbox
    there is no ``clear``/unread concept (no background notifier): the window,
    not read-state, decides what the card shows.

    ``path=None`` keeps it in-memory (the GUI default and tests use this so they
    never touch the repo's ``data/``); ``MainWindow`` injects a real path.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        entries = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)]

    def entries(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._entries]

    def merge(self, items: list[dict[str, Any]]) -> None:
        now = datetime.now(_TZ).isoformat(timespec="seconds")
        self._entries = merge_dean_updates(self._entries, list(items or []), now=now)
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"entries": self._entries}, ensure_ascii=False)
            )
        except OSError:
            pass
