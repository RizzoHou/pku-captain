"""Minimal diff store: pid -> {reply, last_cid, checked_at}. `last_cid` is the
comment-id cursor used to fetch only the new replies; it is an id, not content.
Never stores comment text (anonymous campus speech — no reason to cache it)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# A state mapping is {pid(str): {"reply": int, "checked_at": int, "last_cid"?: int}}.
# last_cid is absent on cold-start entries (added once a hole's comments are fetched).
StateMap = dict[str, dict[str, Any]]


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> StateMap:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def save(self, state: StateMap) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)  # atomic
