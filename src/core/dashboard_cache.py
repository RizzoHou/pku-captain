"""DashboardCache — persist each dashboard card's last-known data to disk so
the panel can paint instantly from saved state on the next launch and only
re-render the cards whose data actually changed.

One JSON file per tool key at ``data/dashboard_cache/<key>.json`` holding
``{"key", "data", "updated_at"}``, where ``data`` is the **raw tool payload**
the dashboard renders from (not the rendered widgets) — so e.g. cached
assignments are re-filtered against today's clock when repainted. Mirrors the
`SessionStore` convention (`src/core/session_store.py`): a ``threading.Lock``
guards every load/modify/write. The store is intentionally dumb — pure
persistence, no in-memory mirror and no change-detection; the GUI layer owns
the "render only if changed" decision (see `MainWindow`), which keeps this
class trivially testable and sidesteps the load-once-stale-mirror footgun the
`MemoryStore` warns about.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "dashboard_cache"


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


class DashboardCache:
    """One-JSON-file-per-card store of the dashboard's last-known data."""

    def __init__(self, directory: Path | str = _DEFAULT_CACHE_DIR) -> None:
        self._dir = Path(directory)
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def save(self, key: str, data: Any) -> None:
        """Write one card's payload through to disk (overwrites).

        ``data`` must be JSON-serializable — it is the same dict/list the
        dashboard setters consume, so this holds for every cached card.
        """
        payload = {"key": key, "data": data, "updated_at": _now_iso()}
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get(self, key: str) -> Any | None:
        """Return one card's cached ``data``, or None if missing/corrupt."""
        with self._lock:
            path = self._path(key)
            if not path.exists():
                return None
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return record.get("data") if isinstance(record, dict) else None

    def load_all(self) -> dict[str, Any]:
        """Return ``{tool_key: data}`` for every cached card.

        Globs the directory and parses each file; corrupt entries are skipped
        so one bad file never blocks the rest of the panel from painting.
        """
        with self._lock:
            if not self._dir.exists():
                return {}
            paths = sorted(self._dir.glob("*.json"))
        result: dict[str, Any] = {}
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(record, dict) or "data" not in record:
                continue
            key = str(record.get("key") or path.stem)
            result[key] = record["data"]
        return result

    def newest_timestamp(self) -> str | None:
        """Return the most recent ``updated_at`` across all cached cards.

        Used to seed the panel's "last saved" label before the first live
        refresh completes. None when nothing is cached yet.
        """
        with self._lock:
            if not self._dir.exists():
                return None
            paths = sorted(self._dir.glob("*.json"))
        stamps: list[str] = []
        for path in paths:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(record, dict) and record.get("updated_at"):
                stamps.append(str(record["updated_at"]))
        return max(stamps) if stamps else None
