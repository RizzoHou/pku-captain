from __future__ import annotations

import json
from pathlib import Path

from src.tools.pku3b_links import (
    Pku3bLinkResolver,
    enrich_announcements,
    enrich_assignments,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_enrich_assignments_adds_course_and_submit_links(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "menu.json",
        {
            "课程作业": (
                "/webapps/blackboard/content/listContent.jsp"
                "?course_id=_98089_1&content_id=_1566122_1&mode=reset"
            ),
            "课程通知": (
                "/webapps/blackboard/content/launchLink.jsp"
                "?course_id=_98089_1&tool_id=_142_1&tool_type=TOOL&mode=view"
            ),
        },
    )
    _write_json(
        tmp_path / "contents.json",
        [
            {
                "id": "_1622080_1",
                "title": "2026-作业十七",
                "kind": "Assignment",
            }
        ],
    )

    records = enrich_assignments(
        [{"course_id": "_98089_1", "title": "2026-作业十七"}],
        resolver=Pku3bLinkResolver(tmp_path),
    )

    assert records[0]["url"] == (
        "https://course.pku.edu.cn/webapps/blackboard/content/listContent.jsp"
        "?course_id=_98089_1&content_id=_1566122_1&mode=reset"
    )
    assert records[0]["blackboard_content_id"] == "_1622080_1"
    assert records[0]["submit_url"] == (
        "https://course.pku.edu.cn/webapps/assignment/uploadAssignment"
        "?content_id=_1622080_1&course_id=_98089_1&group_id=&mode=view"
    )


def test_enrich_announcements_maps_course_name_to_notice_page(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "courses.json",
        [
            [
                "_98208_1",
                "25262-00048-04835230-190****090-00-1: 人工智能基础(25-26学年第2学期)",
                True,
            ]
        ],
    )
    _write_json(
        tmp_path / "menu.json",
        {
            "课程通知": (
                "/webapps/blackboard/content/launchLink.jsp"
                "?course_id=_98208_1&tool_id=_142_1&tool_type=TOOL&mode=view"
            )
        },
    )

    records = enrich_announcements(
        [{"course": "人工智能基础", "title": "复习课通知", "id": "abc12345"}],
        resolver=Pku3bLinkResolver(tmp_path),
    )

    assert records[0]["url"] == (
        "https://course.pku.edu.cn/webapps/blackboard/content/launchLink.jsp"
        "?course_id=_98208_1&tool_id=_142_1&tool_type=TOOL&mode=view"
    )
