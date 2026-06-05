from __future__ import annotations

from datetime import datetime, timedelta

from src.tools.pku3b_coursetable import _parse_course_table
from src.ui.formatters import upcoming_assignments, upcoming_lectures


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
