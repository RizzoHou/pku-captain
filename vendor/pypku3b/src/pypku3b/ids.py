"""Stable content ids for assignments and announcements.

pku3b derives these ids from Rust's ``DefaultHasher`` (SipHash-1-3) over
``(course_id, content_id)``, which is not portable to Python. Nothing in the
downstream consumer re-derives an id against pku3b — ids only need to be stable
and self-consistent (detail-by-id filters a freshly fetched list) — so we use a
BLAKE2b digest truncated to the same 16-hex-char width instead.
"""

from __future__ import annotations

import hashlib


def content_hash(course_id: str, content_id: str) -> str:
    """Return a stable 16-char lowercase-hex id for one course/content pair."""
    payload = f"{course_id}\x00{content_id}".encode("utf-8")
    return hashlib.blake2b(payload, digest_size=8).hexdigest()
