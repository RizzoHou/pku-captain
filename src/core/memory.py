"""Memory backend — a persistent user-preference store.

Core feature #6: "persistent personal-preference memory". This stores
user *preferences* (e.g. "I live in Yan'an Garden", "remind me in
Chinese") — not conversation history, which `Conversation` handles.

`MemoryStore` is deliberately free of any `Tool` dependency so workflows
and the dashboard can reuse it directly. `MemoryTool` (src/tools/memory.py)
is the thin agent-facing wrapper.

Entries are key/value pairs with a write timestamp, persisted to a JSON
file under a gitignored `data/` directory. All public methods are
thread-safe (guarded by a single lock), satisfying the integration
contract's Tool thread-safety requirement.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_PATH = _REPO_ROOT / "data" / "memory.json"


@dataclass(frozen=True)
class MemoryEntry:
    """A single stored preference."""

    key: str
    value: str
    updated_at: str  # ISO-8601, Asia/Shanghai

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class MemoryStore:
    """File-backed key/value preference store.

    A fresh instance loads whatever is already on disk, so persistence
    is verified by constructing a second instance pointed at the same
    file. Every mutation is written through immediately.
    """

    def __init__(self, path: str | Path = DEFAULT_MEMORY_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable file: start empty rather than crash.
            return
        for item in raw.get("entries", []):
            key = item.get("key")
            if not isinstance(key, str):
                continue
            self._entries[key] = MemoryEntry(
                key=key,
                value=str(item.get("value", "")),
                updated_at=str(item.get("updated_at", "")),
            )

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [e.to_dict() for e in self._entries.values()]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -- CRUD ------------------------------------------------------------

    def set(self, key: str, value: str) -> MemoryEntry:
        """Create or overwrite a preference; returns the stored entry."""
        key = key.strip()
        if not key:
            raise ValueError("memory key must be a non-empty string")
        with self._lock:
            entry = MemoryEntry(
                key=key,
                value=value,
                updated_at=datetime.now(_TZ).isoformat(timespec="seconds"),
            )
            self._entries[key] = entry
            self._flush()
            return entry

    def get(self, key: str) -> MemoryEntry | None:
        """Return the entry for `key`, or None if absent."""
        with self._lock:
            return self._entries.get(key.strip())

    def list(self) -> list[MemoryEntry]:
        """Return all entries, sorted by key."""
        with self._lock:
            return [self._entries[k] for k in sorted(self._entries)]

    def delete(self, key: str) -> bool:
        """Remove a preference; returns True if it existed."""
        with self._lock:
            existed = self._entries.pop(key.strip(), None) is not None
            if existed:
                self._flush()
            return existed


_MEMORY_HEADER = "Known facts about the user (from long-term memory):"


def render_memory_context(entries: list[MemoryEntry]) -> str:
    """Render stored entries as a system-prompt block, or "" if empty.

    Folded into the leading system message at each turn so the agent's
    replies reflect what it already knows about the user without having
    to call the `memory` tool first. Pure (no I/O) so it is trivially
    unit-testable in isolation.
    """
    if not entries:
        return ""
    lines = [f"- {entry.key}: {entry.value}" for entry in entries]
    return _MEMORY_HEADER + "\n" + "\n".join(lines)
