"""Shared formatting helpers for GUI data summaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def upcoming_lectures(items: object) -> list[dict[str, Any]]:
    """Return lectures happening today or later, sorted earliest-first.

    The dashboard "讲座推荐" card is a recommendation surface, so it shows only
    upcoming events. Filtering at render time (rather than at fetch via the
    tool's ``start_date``) re-evaluates "today" on every repaint, matching the
    dashboard-cache invariant that raw payloads re-filter against the clock —
    the same pattern as ``upcoming_assignments``. Lectures whose ``time`` is
    missing or unparseable are dropped (a recommendation needs a date), and the
    grain is the date, not the moment, so a lecture earlier today stays visible
    all day.
    """
    if not isinstance(items, list):
        return []

    today = date.today()
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        when = parse_datetime(item.get("time"))
        if when is None or when.date() < today:
            continue
        dated.append((when, item))

    dated.sort(key=lambda pair: pair[0])
    return [item for _, item in dated]


def upcoming_assignments(items: object) -> list[dict[str, Any]]:
    """Return incomplete assignments, sorted with future deadlines first."""
    if not isinstance(items, list):
        return []

    now = datetime.now().astimezone()
    future: list[tuple[datetime, dict[str, Any]]] = []
    no_deadline: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict) or item.get("completed"):
            continue
        deadline = parse_datetime(item.get("deadline_iso"))
        if deadline is None:
            no_deadline.append(item)
        elif deadline >= now:
            future.append((deadline, item))
        else:
            fallback.append(item)

    future.sort(key=lambda pair: pair[0])
    if future:
        return [item for _, item in future] + no_deadline
    return no_deadline + fallback


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed
