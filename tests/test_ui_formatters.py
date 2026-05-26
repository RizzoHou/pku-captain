from __future__ import annotations

from datetime import datetime, timedelta

from src.tools.pku3b_coursetable import _parse_course_table
from src.ui.formatters import upcoming_assignments


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


def test_parse_course_table_merges_contiguous_slots() -> None:
    blocks = _parse_course_table(
        {
            "course": [
                {"mon": {"courseName": "程序设计实习(主) 上课信息：一教101 教师：张三"}},
                {"mon": {"courseName": "程序设计实习(主) 上课信息：一教101 教师：张三"}},
                {"mon": {"courseName": "高等数学(主) 上课信息：二教202 教师：李四"}},
            ]
        }
    )

    assert [(item.title, item.start_slot, item.end_slot) for item in blocks] == [
        ("程序设计实习", 1, 2),
        ("高等数学", 3, 3),
    ]
