"""Persist course announcement history for the dashboard."""

from __future__ import annotations

import json
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HISTORY_PATH = _REPO_ROOT / "data" / "announcement_history.json"
_MAX_HISTORY_ITEMS = 500


class AnnouncementHistoryStore:
    """Small JSON-backed store for previously seen course announcements."""

    def __init__(self, path: Path | str = _DEFAULT_HISTORY_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> list[dict[str, object]]:
        with self._lock:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
        items = data.get("announcements") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def save(self, items: list[dict[str, object]]) -> None:
        normalized = [dict(item) for item in items if isinstance(item, dict)]
        if len(normalized) > _MAX_HISTORY_ITEMS:
            normalized = normalized[-_MAX_HISTORY_ITEMS:]
        payload = {"announcements": normalized}
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
