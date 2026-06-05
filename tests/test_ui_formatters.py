from __future__ import annotations

from datetime import datetime, timedelta

from src.tools.pku3b_coursetable import _parse_course_table
from src.ui.formatters import (
    split_dean_items,
    upcoming_assignments,
    upcoming_lectures,
)

_DEAN_NOW = datetime(2026, 6, 5, 12, 0).astimezone()


def _dean(key, *, source="notice", date="", first_seen=""):
    return {
        "key": key,
        "source": source,
        "source_label": "通知公告",
        "title": key,
        "url": "u",
        "date": date,
        "item_id": "1",
        "first_seen": first_seen,
    }


def test_split_dean_notices_use_one_month_window() -> None:
    fresh = _dean("notice:1", date="2026-06-01")  # ~4 days old → recent
    stale = _dean("notice:2", date="2026-04-01")  # >1 month old → history
    recent, history = split_dean_items([fresh, stale], now=_DEAN_NOW)
    assert [i["key"] for i in recent] == ["notice:1"]
    assert [i["key"] for i in history] == ["notice:2"]


def test_split_dean_others_use_half_year_window() -> None:
    # A download dated 3 months ago stays recent (6-month window), unlike a
    # notice at the same age which would fall into history.
    download = _dean("download:1", source="download", date="2026-03-10")
    recent, history = split_dean_items([download], now=_DEAN_NOW)
    assert [i["key"] for i in recent] == ["download:1"]
    assert history == []


def test_split_dean_dateless_rule_windows_by_first_seen() -> None:
    fresh_rule = _dean(
        "rules_school:1", source="rules_school", first_seen="2026-05-20T09:00:00+08:00"
    )
    old_rule = _dean(
        "rules_school:2", source="rules_school", first_seen="2025-10-01T09:00:00+08:00"
    )
    recent, history = split_dean_items([fresh_rule, old_rule], now=_DEAN_NOW)
    assert [i["key"] for i in recent] == ["rules_school:1"]
    assert [i["key"] for i in history] == ["rules_school:2"]


def test_split_dean_falls_back_to_first_seen_on_unparseable_date() -> None:
    item = _dean("notice:1", date="2026/06/01", first_seen="2026-06-04T09:00:00+08:00")
    recent, history = split_dean_items([item], now=_DEAN_NOW)
    assert [i["key"] for i in recent] == ["notice:1"]
    assert history == []


def test_split_dean_keeps_undated_item_in_history_not_dropped() -> None:
    item = _dean("notice:1")  # no date, no first_seen
    recent, history = split_dean_items([item], now=_DEAN_NOW)
    assert recent == []
    assert [i["key"] for i in history] == ["notice:1"]  # never lost


def test_split_dean_sorts_recent_newest_first() -> None:
    older = _dean("notice:1", date="2026-05-20")
    newer = _dean("notice:2", date="2026-06-02")
    recent, _ = split_dean_items([older, newer], now=_DEAN_NOW)
    assert [i["key"] for i in recent] == ["notice:2", "notice:1"]


def test_upcoming_assignments_prioritizes_future_deadlines() -> None:
    now = datetime.now().astimezone()
    past = (now - timedelta(days=2)).isoformat()
    future_soon = (now + timedelta(days=1)).isoformat()
    future_later = (now + timedelta(days=3)).isoformat()

    result = upcoming_assignments(
        [
            {"title": "past", "deadline_iso": past, "completed": False},
            {"title": "future later", "deadline_iso": future_later, "completed": False},
            {"title": "done", "deadline_iso": future_soon, "completed": True},
            {"title": "future soon", "deadline_iso": future_soon, "completed": False},
            {"title": "no deadline", "deadline_iso": None, "completed": False},
        ]
    )

    assert [item["title"] for item in result] == [
        "future soon",
        "future later",
        "no deadline",
    ]


def test_upcoming_lectures_keeps_today_and_future_sorted() -> None:
    today = datetime.now().astimezone()
    yesterday = (today - timedelta(days=1)).replace(microsecond=0).isoformat()
    earlier_today = today.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    soon = (today + timedelta(days=2)).replace(microsecond=0).isoformat()
    later = (today + timedelta(days=5)).replace(microsecond=0).isoformat()

    result = upcoming_lectures(
        [
            {"title": "past", "time": yesterday},
            {"title": "later", "time": later},
            {"title": "today", "time": earlier_today},
            {"title": "no time", "time": ""},
            {"title": "soon", "time": soon},
            "not a dict",
        ]
    )

    assert [item["title"] for item in result] == ["today", "soon", "later"]


def test_upcoming_lectures_handles_non_list() -> None:
    assert upcoming_lectures(None) == []
    assert upcoming_lectures("nope") == []


def test_parse_course_table_merges_contiguous_slots() -> None:
    blocks = _parse_course_table(
        {
            "course": [
                {
                    "mon": {
                        "courseName": (
                            "程序设计实习(主) 上课信息：一教101 教师：张三 "
                            "备注：与软件设计实践互斥 考试信息：20260626"
                        )
                    }
                },
                {
                    "mon": {
                        "courseName": (
                            "程序设计实习(主) 上课信息：一教101 教师：张三 "
                            "备注：与软件设计实践互斥 考试信息：20260626"
                        )
                    }
                },
                {"mon": {"courseName": "高等数学(主) 上课信息：二教202 教师：李四"}},
            ]
        }
    )

    assert [(item.title, item.start_slot, item.end_slot) for item in blocks] == [
        ("程序设计实习", 1, 2),
        ("高等数学", 3, 3),
    ]
    assert blocks[0].note == "与软件设计实践互斥"


def test_parse_course_table_multi_session_cell_does_not_leak() -> None:
    """A cell holding two sessions of the same course must keep each field
    bounded to its own session: 考试信息 must not swallow the next session's
    text, and both rooms should surface under 上课信息."""
    blocks = _parse_course_table(
        {
            "course": [
                {
                    "mon": {
                        "courseName": (
                            "程序设计实习(主)<br>上课信息：8-8周 每周 理教208 "
                            "教师：杨帅 备注：与软件设计实践互斥<br>"
                            "考试信息：20260626 星期五 下午 <br>"
                            "程序设计实习(主)<br>上课信息：1-15周 每周 理教407 "
                            "教师：杨帅 备注：与软件设计实践互斥<br>"
                            "考试信息：20260626 星期五 下午 "
                        )
                    }
                }
            ]
        }
    )

    assert len(blocks) == 1
    block = blocks[0]
    assert block.title == "程序设计实习"
    assert block.note == "与软件设计实践互斥"
    # 考试信息 stops at its own session — no leaked "程序设计实习(主)" tail.
    assert block.detail == (
        "上课信息：8-8周 每周 理教208；1-15周 每周 理教407\n"
        "教师：杨帅\n"
        "考试信息：20260626 星期五 下午"
    )
    assert "(主)" not in block.detail
