"""Parser regression tests pinned to captured fixtures.

The fixtures in ``tests/fixtures/`` are real authenticated pages saved during
development. If P-Lib changes its markup, these tests break — which is the
point: the scraper's assumptions are made visible and enforced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plib_cli.parsers import parse_material, parse_profile, parse_search

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://pkuhub.cn"


@pytest.fixture
def search_html() -> str:
    return (FIXTURES / "search.html").read_text(encoding="utf-8")


@pytest.fixture
def material_html() -> str:
    return (FIXTURES / "material.html").read_text(encoding="utf-8")


@pytest.fixture
def profile_html() -> str:
    return (FIXTURES / "profile.html").read_text(encoding="utf-8")


def test_search_returns_full_page(search_html: str) -> None:
    page = parse_search(search_html, query="高等数学", page=1, base_url=BASE)
    assert page.total == 44
    assert len(page.results) == 10


def test_search_result_fields(search_html: str) -> None:
    page = parse_search(search_html, query="高等数学", page=1, base_url=BASE)
    by_id = {r.id: r for r in page.results}
    r = by_id[1064]
    assert r.title == "高等数学A期中考试2025年试题"
    assert r.type == "试卷"
    assert r.course == "高等数学A（一）"
    assert r.department == "数学科学学院"
    assert r.semester == "2025年秋季"
    assert r.uploader == "虚怀若谷"
    assert r.date == "2025-11-06"
    assert r.downloads == 52
    assert r.views == 138
    assert r.favorites == 0
    assert r.url == f"{BASE}/material/1064"


def test_search_ids_are_unique_and_int(search_html: str) -> None:
    page = parse_search(search_html, query="x", page=1, base_url=BASE)
    ids = [r.id for r in page.results]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, int) for i in ids)


def test_material_detail(material_html: str) -> None:
    m = parse_material(material_html, mid=727, base_url=BASE)
    assert m.id == 727
    assert m.title == "英语名著与电影 小测与期末考 资料"
    assert m.type == "汇编"
    assert m.course == "英语名著与电影"
    assert m.course_id == 1952
    assert m.department == "外国语学院"
    assert m.department_id == 23
    assert m.semester == "2025春"
    assert m.uploader == "joker_ceva"
    assert m.upload_time == "2025-06-11 22:31"
    assert m.downloads == 816
    assert m.views == 1388
    assert m.file_type == "ZIP"
    assert m.description and "往年题" in m.description
    assert m.download_url == f"{BASE}/download/727"
    # File tree parsed (this material is a populated zip); names are non-empty.
    assert m.files
    assert all(isinstance(f, str) and f for f in m.files)


def test_profile_quota(profile_html: str) -> None:
    # The server's authoritative "remaining downloads today" — the figure that
    # replaced the old local counter. Drift in the 今日剩余下载次数 markup breaks
    # this loudly instead of silently returning None at runtime.
    p = parse_profile(profile_html)
    assert p.download_remaining == 6


def test_search_sort_values_match_site(search_html: str) -> None:
    import re

    from plib_cli.cli import SORT_CHOICES

    block = re.search(r'<select[^>]*name="sort".*?</select>', search_html, re.S)
    assert block
    values = re.findall(r'value="([^"]*)"', block.group(0))
    assert set(SORT_CHOICES) == {v for v in values if v}
