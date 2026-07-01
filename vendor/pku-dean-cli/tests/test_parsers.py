from __future__ import annotations

import pytest

from dean.errors import DeanError
from dean.parsers import (
    parse_files,
    parse_guide,
    parse_notice_doc,
    parse_notices,
    parse_rule_doc,
    parse_rules,
    parse_sidebar,
)


def test_sidebar_grouped_by_category(fixture):
    links = parse_sidebar(fixture("index.html"))
    assert links, "expected sidebar links"
    # Only student_info / service links, never teacher_info.
    assert all("teacher_info.php" not in link.url for link in links)
    categories = {link.category for link in links}
    assert "选课和退课" in categories or any("选课" in c for c in categories)
    # Each link is absolute and titled.
    sample = links[1]
    assert sample.url.startswith("https://")
    assert sample.title


def test_rules_school_paginated(fixture):
    page = parse_rules(fixture("rules_school.html"), scope="school")
    assert page.last_page == 6
    assert page.page == 1
    assert len(page.items) == 15
    first = page.items[0]
    assert first.scope == "school"
    assert first.id > 0
    assert "rules_info.php" in first.url


def test_rules_national_single_page(fixture):
    page = parse_rules(fixture("rules_national.html"), scope="national")
    assert page.last_page == 1
    assert all(item.scope == "national" for item in page.items)
    # IDs are unique (sidebar nav links must not leak in).
    ids = [i.id for i in page.items]
    assert len(ids) == len(set(ids))


def test_rule_doc_valid(fixture):
    doc = parse_rule_doc(fixture("rule_valid.html"), 20, "http://x/rules_info.php?id=20")
    assert "学籍管理办法" in doc.title
    assert len(doc.text) > 1000


def test_rule_doc_missing_raises_not_found(fixture):
    with pytest.raises(DeanError) as exc:
        parse_rule_doc(fixture("rule_missing.html"), 99999999, "http://x")
    assert exc.value.code == "not_found"


def test_guide_valid(fixture):
    doc = parse_guide(fixture("guide_valid.html"), 15, "http://x/student_info.php?id=15")
    assert doc.title == "选课"
    assert doc.update_date == "2021-09-01"
    headings = [s.heading for s in doc.sections]
    assert "服务描述" in headings and "服务流程" in headings
    assert all(s.body for s in doc.sections)
    # Related links are classified and a policy link points at a fetchable rule.
    groups = {r.group for r in doc.related}
    assert "policy" in groups
    policy = next(r for r in doc.related if r.group == "policy")
    assert "rules_info.php" in policy.url


def test_guide_missing_raises_not_found(fixture):
    with pytest.raises(DeanError) as exc:
        parse_guide(fixture("guide_missing.html"), 99999, "http://x")
    assert exc.value.code == "not_found"


def test_notices_listing_paginated(fixture):
    page = parse_notices(fixture("notice_list.html"))
    assert page.page == 1
    assert page.last_page == 45
    assert len(page.items) == 15
    first = page.items[0]
    assert first.id > 0
    assert "notice_details.php" in first.url
    assert first.date == "2026-06-03"
    # IDs are unique.
    ids = [i.id for i in page.items]
    assert len(ids) == len(set(ids))


def test_notice_doc_valid(fixture):
    doc = parse_notice_doc(
        fixture("notice_valid.html"), 743, "http://x/notice_details.php?id=743"
    )
    assert "期末考试" in doc.title
    assert doc.date == "2026-05-20"
    assert len(doc.text) > 500
    # The heading, date span, and share widget are stripped from the body.
    assert "分享到" not in doc.text
    assert doc.text.startswith("根据我校教学进程")


def test_notice_doc_missing_raises_not_found(fixture):
    with pytest.raises(DeanError) as exc:
        parse_notice_doc(fixture("notice_missing.html"), 99999999, "http://x")
    assert exc.value.code == "not_found"


def test_download_listing(fixture):
    page = parse_files(fixture("download.html"), kind="download")
    assert page.last_page >= 1
    assert page.items
    item = page.items[0]
    assert item.kind == "download"
    assert "type=down" in item.download_url
    assert item.downloads is not None
    assert item.date


def test_openinfo_listing(fixture):
    page = parse_files(fixture("openinfo.html"), kind="openinfo")
    assert page.items
    assert all("type=msg" in i.download_url for i in page.items)
