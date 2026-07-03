"""Chinese date-string parsing helpers.

Blackboard deadline strings and announcement 发布时间 lines are always Beijing
time; the ISO output is pinned to ``+08:00`` regardless of the host TZ (matching
pku3b's ``render_json``, which deliberately fixes the offset so a UTC host does
not mis-tag the instant).
"""

from __future__ import annotations

import re

# e.g. "2026年4月4日 星期五 下午11:59"
_DEADLINE_RE = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*星期.\s*(上午|下午)(\d{1,2}):(\d{1,2})"
)
# e.g. "发布时间：2026年6月1日" — day-granular only (matches pku3b's date pass).
_DATE_RE = re.compile(r"(\d+)年(\d+)月(\d+)日")


def parse_deadline_iso(raw: str | None) -> str | None:
    """Parse a raw Blackboard deadline string into an ISO-8601 ``+08:00`` stamp.

    Returns ``None`` when *raw* is falsy or does not match. ``下午`` (PM) adds 12
    hours unless the hour is already >= 12, exactly like pku3b's ``deadline()``.
    """
    if not raw:
        return None
    match = _DEADLINE_RE.search(raw)
    if match is None:
        return None
    year, month, day, meridiem, hour_s, minute_s = match.groups()
    hour = int(hour_s)
    minute = int(minute_s)
    if meridiem == "下午" and hour < 12:
        hour += 12
    try:
        # Validate the components without importing a TZ library; we always
        # tag +08:00 rather than converting.
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return (
            f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            f"T{hour:02d}:{minute:02d}:00+08:00"
        )
    except ValueError:
        return None


def parse_posted_date(text: str | None) -> str | None:
    """Extract an ISO ``YYYY-MM-DD`` date from a 发布时间 line, or ``None``."""
    if not text:
        return None
    match = _DATE_RE.search(text)
    if match is None:
        return None
    year, month, day = (int(group) for group in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"
