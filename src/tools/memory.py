"""MemoryTool — agent-facing wrapper over the user-preference store.

Lets the agent persist and recall user preferences across sessions
(core feature #6). The actual storage lives in `src.core.memory.MemoryStore`;
this Tool only dispatches on an `action` argument and shapes results into
`ToolResult`. Purely local — offline-safe — so bootstrap registers it in
both the online and offline tool sets.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.memory import MemoryStore
from .base import Tool, ToolResult


class MemoryTool(Tool):
    name: ClassVar[str] = "memory"
    description: ClassVar[str] = (
        "Persistent store for user preferences (e.g. where the user lives, "
        "their class schedule, preferred reply language). Use it to remember "
        "facts the user states about themselves and to recall them later. "
        "Dispatches on `action`: remember / set / get / list / delete. "
        "Prefer `remember` (just a free-text fact, no key) for things you "
        "learn in conversation; use `set` only when overwriting a known key."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["remember", "set", "get", "list", "delete"],
                "description": (
                    "remember: store a free-text fact, key auto-derived "
                    "(needs text). "
                    "set: store/overwrite under an explicit key (needs key + value). "
                    "get: read one preference (needs key). "
                    "list: return all stored preferences (no other args). "
                    "delete: remove a preference (needs key)."
                ),
            },
            "text": {
                "type": "string",
                "description": (
                    "A natural-language fact about the user to remember, "
                    "e.g. '住在燕园'. Required for remember."
                ),
            },
            "key": {
                "type": "string",
                "description": (
                    "Short stable identifier for the preference, e.g. "
                    "'home_location'. Required for set / get / delete."
                ),
            },
            "value": {
                "type": "string",
                "description": "The preference text to store. Required for set.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store if store is not None else MemoryStore()

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = (args.get("action") or "").strip()
        if action == "remember":
            return self._remember(args)
        if action == "set":
            return self._set(args)
        if action == "get":
            return self._get(args)
        if action == "list":
            return self._list()
        if action == "delete":
            return self._delete(args)
        return ToolResult(
            success=False,
            error=(
                f"unknown action: {action!r} "
                "(expected remember/set/get/list/delete)"
            ),
        )

    def _remember(self, args: dict[str, Any]) -> ToolResult:
        text = (args.get("text") or "").strip()
        if not text:
            return ToolResult(success=False, error="`remember` requires non-empty `text`")
        entry = self._store.remember(text)
        return ToolResult(success=True, data=entry.to_dict())

    def _set(self, args: dict[str, Any]) -> ToolResult:
        key = (args.get("key") or "").strip()
        if not key:
            return ToolResult(success=False, error="`set` requires a non-empty `key`")
        if "value" not in args or args.get("value") is None:
            return ToolResult(success=False, error="`set` requires a `value`")
        entry = self._store.set(key, str(args["value"]))
        return ToolResult(success=True, data=entry.to_dict())

    def _get(self, args: dict[str, Any]) -> ToolResult:
        key = (args.get("key") or "").strip()
        if not key:
            return ToolResult(success=False, error="`get` requires a non-empty `key`")
        entry = self._store.get(key)
        if entry is None:
            return ToolResult(success=False, error=f"no preference stored for {key!r}")
        return ToolResult(success=True, data=entry.to_dict())

    def _list(self) -> ToolResult:
        return ToolResult(
            success=True,
            data=[entry.to_dict() for entry in self._store.list()],
        )

    def _delete(self, args: dict[str, Any]) -> ToolResult:
        key = (args.get("key") or "").strip()
        if not key:
            return ToolResult(success=False, error="`delete` requires a non-empty `key`")
        if self._store.delete(key):
            return ToolResult(success=True, data={"deleted": key})
        return ToolResult(success=False, error=f"no preference stored for {key!r}")
