"""Shared formatting helpers for GUI data summaries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


_DEAN_WINDOW_DAYS: dict[str, int] = {"notice": 31}
_DEAN_DEFAULT_WINDOW_DAYS = 183

# Course-notice 最近 window — same 1-month span as a dean notice.
_ANNOUNCEMENT_WINDOW_DAYS = 31


def recent_announcements(
    items: object, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Return course announcements posted within the last month, newest-first.

    Drives the 课程通知 card's 最近 section. ``announcement list`` carries no
    dates, so :class:`~src.tools.pku3b_announcements.PKU3bAnnouncementsTool`
    attaches a ``posted_date`` (ISO ``YYYY-MM-DD``) when invoked with
    ``resolve_dates``. Items whose date is missing or unparseable — pku3b
    reports none for roughly half of announcements — are excluded from 最近
    (they remain in 历史通知, which shows every item). Filtering at render time
    re-evaluates the window against today's clock on every repaint, matching
    the dashboard-cache invariant.
    """
    if not isinstance(items, list):
        return []
    current = now or datetime.now().astimezone()
    # posted_date is day-granular, so window by date — otherwise an item posted
    # exactly a month ago would flicker in/out depending on the repaint's
    # time of day.
    cutoff = (current - timedelta(days=_ANNOUNCEMENT_WINDOW_DAYS)).date()

    dated: list[tuple[datetime, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        when = parse_datetime(item.get("posted_date"))
        if when is None or when.date() < cutoff:
            continue
        dated.append((when, item))

    dated.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in dated]


def split_dean_items(
    entries: object, now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split accumulated dean items into ``(recent, history)`` by recency window.

    Notices are kept ~1 month; every other source (校级/上级 rules, downloads,
    openinfo) ~half a year. The effective date is the item's own ``date`` when
    parseable, else the ``first_seen`` stamp the inbox records — so date-less
    rules window by when we first saw them (they fall into history ~6 months
    later, never lost). Filtering at render time re-evaluates the window against
    today's clock on every repaint, matching the dashboard-cache invariant. Both
    lists are newest-first. No item is ever dropped: anything outside its window
    (or with no usable date) lands in history.
    """
    if not isinstance(entries, list):
        return [], []
    current = now or datetime.now().astimezone()

    recent: list[tuple[datetime, dict[str, Any]]] = []
    history: list[tuple[datetime | None, dict[str, Any]]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        when = parse_datetime(item.get("date")) or parse_datetime(item.get("first_seen"))
        days = _DEAN_WINDOW_DAYS.get(
            str(item.get("source") or ""), _DEAN_DEFAULT_WINDOW_DAYS
        )
        cutoff = current - timedelta(days=days)
        if when is not None and when >= cutoff:
            recent.append((when, item))
        else:
            history.append((when, item))

    epoch = datetime.min.replace(tzinfo=UTC)
    recent.sort(key=lambda pair: pair[0], reverse=True)
    history.sort(key=lambda pair: pair[0] or epoch, reverse=True)
    return [item for _, item in recent], [item for _, item in history]


# Canonical category order + Chinese labels for the dean message columns, kept
# in sync with ``DeanUpdatesTool._SOURCES``. Drives the per-category columns in
# ``DeanMessagesDialog`` so every tab lists categories in the same stable order.
DEAN_CATEGORY_ORDER: tuple[tuple[str, str], ...] = (
    ("notice", "通知公告"),
    ("rules_school", "校级规章"),
    ("rules_national", "上级文件"),
    ("download", "资料下载"),
    ("openinfo", "信息公开"),
)


def group_dean_by_category(
    items: object,
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """Group dean items into ``(source, label, items)`` columns, canonical order.

    Known sources appear in ``DEAN_CATEGORY_ORDER`` even when empty (the dialog
    renders a （暂无） column so the grid never looks broken); any unknown source
    is appended after, labelled by its own ``source_label``. Item order within a
    column is preserved from the input (``split_dean_items`` already sorts
    newest-first), and no item is ever dropped.
    """
    buckets: dict[str, list[dict[str, Any]]] = {src: [] for src, _ in DEAN_CATEGORY_ORDER}
    labels: dict[str, str] = dict(DEAN_CATEGORY_ORDER)
    extra_order: list[str] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if source not in buckets:
                buckets[source] = []
                extra_order.append(source)
                labels[source] = str(item.get("source_label") or source or "其他")
            buckets[source].append(item)
    ordered = [src for src, _ in DEAN_CATEGORY_ORDER] + extra_order
    return [(src, labels.get(src, src), buckets[src]) for src in ordered]


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
