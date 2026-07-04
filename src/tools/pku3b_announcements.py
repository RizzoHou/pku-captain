"""PKU3bAnnouncementsTool — list course announcements from PKU 教学网.

Counterpart of :class:`~src.tools.pku3b_assignments.PKU3bAssignmentsTool`,
driving the vendored :mod:`pypku3b` library **in-process**. Unlike the old
subprocess path, ``pypku3b`` scrapes each announcement's posted time and body
inline, so a date needs no extra fetch and there is no on-disk date cache:

* No ``announcement_id`` — list mode: ``{index, course, title, id, url,
  posted_date, posted_at}`` per announcement.
* ``announcement_id`` given — detail mode: one announcement's full title,
  posted time, and body (resolved by filtering the list, no extra request).
  An id missing from the current-term list is retried across all terms, so
  history entries that outlived the term still resolve.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_TIMEOUT,
    PKU_SECRETS_DIR,
    ClientFactory,
    Pku3bError,
    default_client_factory,
    secret_values,
    stored_credentials,
)
from .redact import redact

_POSTED_PREFIX = re.compile(r"^\s*发布时间[:：]\s*")


class PKU3bAnnouncementsTool(Tool):
    name: ClassVar[str] = "pku3b_announcements"
    description: ClassVar[str] = (
        "List course announcements (公告/通知) from PKU 教学网 (Blackboard). "
        "With no arguments, returns every announcement's course, title, id, "
        "posted date, and link. Pass `announcement_id` to fetch one "
        "announcement's full title, posted time, and body text. Pass `course` "
        "to filter the list to a course by name substring. Use this to answer "
        "questions like “有什么课程公告？” / “程设最近发了什么通知？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "announcement_id": {
                "type": "string",
                "description": (
                    "If set, fetch the full detail of a single announcement "
                    "by its id (from a prior list call) instead of listing."
                ),
            },
            "course": {
                "type": "string",
                "description": (
                    "List mode only: keep only announcements whose course "
                    "name contains this substring (case-insensitive)."
                ),
            },
            "all_term": {
                "type": "boolean",
                "description": (
                    "Include announcements from all terms, not just the "
                    "current one. Default: false."
                ),
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": (
                    "List mode only: cap the number of announcements "
                    "returned (after filtering). Omit for no cap."
                ),
                "minimum": 1,
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Force a refresh from the server instead of using the "
                    "in-process cache. Default: false."
                ),
                "default": False,
            },
            "resolve_dates": {
                "type": "boolean",
                "description": (
                    "Deprecated/no-op: posted dates are now attached inline in "
                    "every list call (in-process resolution is free)."
                ),
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        secrets_dir: Path | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self.secrets_dir = secrets_dir or PKU_SECRETS_DIR
        self._client_factory = client_factory or default_client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        announcement_id = args.get("announcement_id")
        all_term = bool(args.get("all_term", False))
        force = bool(args.get("force", False))
        try:
            client = self._client_factory(
                secrets_dir=self.secrets_dir,
                timeout=self.timeout,
                credentials=stored_credentials(self.secrets_dir),
            )
            announcements = client.list_announcements(all_term=all_term, force=force)
            if announcement_id is not None:
                wanted = str(announcement_id).strip()
                # History entries outlive the current-term list (term rotation),
                # so a miss there is retried across all terms before failing.
                if (
                    wanted
                    and not all_term
                    and all(wanted not in _candidate_ids(a) for a in announcements)
                ):
                    announcements = client.list_announcements(all_term=True, force=force)
        except Pku3bError as exc:
            message = getattr(exc, "message", str(exc))
            return ToolResult(
                success=False,
                error=redact(message, secret_values(self.secrets_dir)),
            )

        if announcement_id is not None:
            return self._show(str(announcement_id).strip(), announcements)
        return self._list(announcements, args)

    def _list(self, announcements: list[Any], args: dict[str, Any]) -> ToolResult:
        records = [_to_record(a) for a in announcements]
        total = len(records)

        course = args.get("course")
        if course:
            needle = str(course).casefold()
            records = [r for r in records if needle in str(r["course"]).casefold()]

        limit = args.get("limit")
        if limit is not None:
            records = records[: int(limit)]

        return ToolResult(
            success=True,
            data={
                "announcements": records,
                "count": len(records),
                "total_reported": total,
            },
        )

    def _show(self, announcement_id: str, announcements: list[Any]) -> ToolResult:
        if not announcement_id:
            return ToolResult(
                success=False, error="announcement_id must be a non-empty string"
            )
        match = next(
            (a for a in announcements if announcement_id in _candidate_ids(a)), None
        )
        if match is None:
            return ToolResult(
                success=False,
                error=f"announcement with id {announcement_id} not found",
            )
        return ToolResult(
            success=True,
            data={
                "announcement": {
                    "id": _stable_id(match),
                    "course": match.course,
                    "title": match.title,
                    "posted_at": _posted_at(match.posted_time),
                    "body": match.body,
                }
            },
        )


def _posted_at(posted_time: str | None) -> str | None:
    """Strip the leading ``发布时间:`` label from the raw posted-time string."""
    if not posted_time:
        return None
    return _POSTED_PREFIX.sub("", posted_time).strip() or None


def _stable_id(a: Any) -> str:
    """Content-stable announcement id that survives scrape reordering.

    pypku3b's ``a.id`` is *positional* — ``content_hash(course_id,
    "{course_id}_{idx}")`` where ``idx`` is the row's index in a single scrape —
    so it shifts whenever a course's announcement set changes (a new post,
    deletion, or reorder). The dashboard accumulates ids across scrapes into
    ``data/announcement_history.json``; once the set drifts, a stored positional
    id matches nothing on re-list and detail fails with "announcement with id …
    not found". Derive the id from the announcement's own content instead —
    ``(course_id, title, date)`` — so a re-listed announcement re-derives the
    *same* id it had when stored. Undated rows (the body-snippet fallbacks
    pypku3b emits) drop the date component. 16 hex chars, matching pypku3b's
    ``content_hash`` width.
    """
    course_id = str(a.course_id or "").strip()
    title = str(a.title or "").strip()
    date = str(a.posted_date or "").strip()
    parts = [course_id, title, date] if date else [course_id, title]
    payload = "\x00".join(parts).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def _candidate_ids(a: Any) -> set[str]:
    """Ids a stored/queried id may match for this announcement.

    The content-stable id (new, canonical) plus pypku3b's legacy positional
    ``a.id``. Dual-matching keeps legacy history ids that have *not* yet drifted
    resolvable during the migration window, while new rows resolve by stable id.
    """
    return {_stable_id(a), str(a.id)}


def _to_record(a: Any) -> dict[str, Any]:
    return {
        "index": a.index,
        "course": a.course,
        "course_id": a.course_id,
        "title": a.title,
        "id": _stable_id(a),
        "url": a.course_url,
        "posted_date": a.posted_date,
        "posted_at": _posted_at(a.posted_time),
    }
