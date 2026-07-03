"""A tiny content-addressed TTL cache, mirroring pku3b's ``with_cache``.

Each key maps to one JSON file named by a hash of the key; a read hits only when
the file's mtime is within *ttl*. This preserves pku3b's performance profile
(the per-course Blackboard crawl is expensive and is memoized for ~1h) without
its Rust-specific ``TypeId`` framing. Passing ``ttl=None`` (force refresh) makes
every read miss.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable


class Cache:
    def __init__(self, directory: Path | str | None, *, default_ttl: float = 3600.0) -> None:
        self.directory = Path(directory) if directory is not None else None
        self.default_ttl = default_ttl

    def _path(self, key: str) -> Path | None:
        if self.directory is None:
            return None
        digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()
        return self.directory / f"cache-{digest}.json"

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], Any],
        *,
        ttl: float | None = None,
        force: bool = False,
    ) -> Any:
        """Return the cached value for *key*, or compute+store it.

        ``ttl=None`` uses ``default_ttl``; ``force=True`` bypasses the read
        (still writes back), matching pku3b's ``--force`` semantics. A disabled
        cache (``directory is None``) always computes.
        """
        path = self._path(key)
        effective_ttl = self.default_ttl if ttl is None else ttl
        if path is not None and not force and path.exists():
            age = time.time() - path.stat().st_mtime
            if age < effective_ttl:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass  # treat as miss

        value = compute()

        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write: two dashboard cards may compute the same key
                # concurrently (assignments + announcements share Blackboard
                # keys); os.replace avoids a torn read that would look corrupt.
                tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{id(value)}")
                tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, path)
            except OSError:
                pass  # cache write failures are non-fatal
        return value
