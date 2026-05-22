"""ReminderTool — create, list, complete, and delete time-bound reminders.

Part of the core feature #3 tool set. A reminder is a *time-bound to-do*
("submit assignment at 10am tomorrow") — distinct from long-term
preference memory (task 003), which the agent stores separately.

v1 is storage + querying only: there is no background timer firing
notifications. `ReminderStore` persists entries to a gitignored JSON file
and guards every read/modify/write with a lock, so `invoke()` is safe to
call from the `AgentWorker` QThread (integration contract §5).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .base import Tool, ToolResult

_TZ = ZoneInfo("Asia/Shanghai")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STORE_PATH = _REPO_ROOT / "data" / "reminders.json"


def _now() -> datetime:
    return datetime.now(_TZ)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string; assume Asia/Shanghai if no offset given."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt


@dataclass
class Reminder:
    """A single time-bound to-do entry."""

    id: int
    text: str
    trigger_time: str  # ISO-8601
    created_time: str  # ISO-8601
    done: bool = False


class ReminderStore:
    """JSON-file-backed reminder store; thread-safe.

    Each public method takes the lock for the whole load/modify/save
    cycle, so concurrent `invoke()` calls cannot interleave a write.
    """

    def __init__(self, path: Path | str = _DEFAULT_STORE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> list[Reminder]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [Reminder(**item) for item in raw]
        except (json.JSONDecodeError, OSError, TypeError):
            # Corrupt or unreadable store: start clean rather than crash
            # the tool. A subsequent _save() overwrites the bad file.
            return []

    def _save(self, reminders: list[Reminder]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(r) for r in reminders], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, text: str, trigger_time: str) -> Reminder:
        with self._lock:
            reminders = self._load()
            next_id = max((r.id for r in reminders), default=0) + 1
            reminder = Reminder(
                id=next_id,
                text=text,
                trigger_time=trigger_time,
                created_time=_now().isoformat(timespec="seconds"),
                done=False,
            )
            reminders.append(reminder)
            self._save(reminders)
            return reminder

    def list(self, *, future_only: bool = False, pending_only: bool = False) -> list[Reminder]:
        with self._lock:
            reminders = self._load()
        if pending_only:
            reminders = [r for r in reminders if not r.done]
        if future_only:
            now = _now()
            reminders = [r for r in reminders if _parse_iso(r.trigger_time) >= now]
        return sorted(reminders, key=lambda r: r.trigger_time)

    def set_done(self, reminder_id: int) -> Reminder | None:
        with self._lock:
            reminders = self._load()
            for r in reminders:
                if r.id == reminder_id:
                    r.done = True
                    self._save(reminders)
                    return r
            return None

    def delete(self, reminder_id: int) -> Reminder | None:
        with self._lock:
            reminders = self._load()
            for i, r in enumerate(reminders):
                if r.id == reminder_id:
                    removed = reminders.pop(i)
                    self._save(reminders)
                    return removed
            return None


class ReminderTool(Tool):
    name: ClassVar[str] = "reminder"
    description: ClassVar[str] = (
        "Manage time-bound reminders (to-dos with a trigger time). "
        "Dispatches on `action`: `add` creates a reminder (needs `text` and "
        "`trigger_time`); `list` returns reminders, optionally filtered to "
        "future-only and/or pending-only; `done` marks a reminder complete by "
        "`id`; `delete` removes a reminder by `id`. Storage only — it does not "
        "fire notifications."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "done", "delete"],
                "description": "Which operation to perform.",
            },
            "text": {
                "type": "string",
                "description": "Reminder text. Required for `add`.",
            },
            "trigger_time": {
                "type": "string",
                "description": (
                    "When the reminder is due, as an ISO-8601 string "
                    "(e.g. '2026-06-06T10:00:00'). Required for `add`."
                ),
            },
            "id": {
                "type": "integer",
                "description": "Reminder id. Required for `done` and `delete`.",
            },
            "future_only": {
                "type": "boolean",
                "description": "For `list`: keep only reminders whose trigger time is not past.",
            },
            "pending_only": {
                "type": "boolean",
                "description": "For `list`: keep only reminders that are not yet done.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, store: ReminderStore | None = None) -> None:
        self._store = store if store is not None else ReminderStore()

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = args.get("action")
        try:
            if action == "add":
                return self._add(args)
            if action == "list":
                return self._list(args)
            if action == "done":
                return self._done(args)
            if action == "delete":
                return self._delete(args)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=False, error=f"unknown action: {action!r}")

    def _add(self, args: dict[str, Any]) -> ToolResult:
        text = (args.get("text") or "").strip()
        trigger_time = (args.get("trigger_time") or "").strip()
        if not text:
            return ToolResult(success=False, error="`add` requires non-empty `text`.")
        if not trigger_time:
            return ToolResult(success=False, error="`add` requires `trigger_time`.")
        _parse_iso(trigger_time)  # validate ISO-8601; raises ValueError on bad input
        reminder = self._store.add(text, trigger_time)
        return ToolResult(success=True, data=asdict(reminder))

    def _list(self, args: dict[str, Any]) -> ToolResult:
        reminders = self._store.list(
            future_only=bool(args.get("future_only", False)),
            pending_only=bool(args.get("pending_only", False)),
        )
        return ToolResult(success=True, data=[asdict(r) for r in reminders])

    def _done(self, args: dict[str, Any]) -> ToolResult:
        reminder_id = args.get("id")
        if not isinstance(reminder_id, int):
            return ToolResult(success=False, error="`done` requires an integer `id`.")
        reminder = self._store.set_done(reminder_id)
        if reminder is None:
            return ToolResult(success=False, error=f"no reminder with id {reminder_id}")
        return ToolResult(success=True, data=asdict(reminder))

    def _delete(self, args: dict[str, Any]) -> ToolResult:
        reminder_id = args.get("id")
        if not isinstance(reminder_id, int):
            return ToolResult(success=False, error="`delete` requires an integer `id`.")
        reminder = self._store.delete(reminder_id)
        if reminder is None:
            return ToolResult(success=False, error=f"no reminder with id {reminder_id}")
        return ToolResult(success=True, data=asdict(reminder))
