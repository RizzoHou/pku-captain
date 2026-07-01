"""HTML → dataclass parsers for P-Lib's server-rendered pages.

The site has no API, so everything is scraped. These parsers are pinned to
the markup captured in ``tests/fixtures/`` and covered by ``test_parsers.py``
— if P-Lib changes its templates, those tests fail loudly rather than the
client returning silently-wrong data. Selectors prefer stable anchors
(``/course/<id>`` links, labelled fields, fa-* icons) over volatile Tailwind
class soup.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .models import Material, Profile, SearchPage, SearchResult

# Closed set of material types, taken from the search filter UI. Used to pick
# the type badge out of the page without depending on its CSS classes.
KNOWN_TYPES = {"习题", "其他", "汇编", "笔记", "答案", "试卷", "课件", "课本"}

_INT_RE = re.compile(r"-?\d+")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _int(text: str | None) -> int | None:
    if not text:
        return None
    m = _INT_RE.search(text)
    return int(m.group()) if m else None


def _id_from_href(href: str | None, kind: str) -> int | None:
    m = re.search(rf"/{kind}/(\d+)", href or "")
    return int(m.group(1)) if m else None


def _icon_text(scope, icon_class: str) -> str | None:
    """Text of the element wrapping an ``<i class="fa-... icon_class">`` icon."""
    icon = scope.select_one(f"i.{icon_class}")
    if icon is None or icon.parent is None:
        return None
    return icon.parent.get_text(strip=True) or None


def _type_badge(scope) -> str | None:
    for span in scope.select("span"):
        text = span.get_text(strip=True)
        if text in KNOWN_TYPES:
            return text
    return None


def parse_search(html: str, query: str, page: int, base_url: str) -> SearchPage:
    soup = _soup(html)
    results: list[SearchResult] = []

    for card in soup.select("div.bg-white.p-4.rounded.shadow"):
        anchor = card.select_one('a[href^="/material/"]')
        if anchor is None:
            continue
        mid = _id_from_href(anchor.get("href"), "material")
        if mid is None:
            continue

        course_a = card.select_one('a[href^="/course/"]')
        dept_a = card.select_one('a[href^="/department/"]')
        user_a = card.select_one('a[href^="/user/"]')
        desc_el = card.select_one("p.text-gray-600")

        results.append(
            SearchResult(
                id=mid,
                title=anchor.get_text(strip=True),
                type=_type_badge(card),
                description=desc_el.get_text(strip=True) if desc_el else None,
                course=course_a.get_text(strip=True) if course_a else None,
                department=dept_a.get_text(strip=True) if dept_a else None,
                semester=_icon_text(card, "fa-calendar-alt"),
                uploader=user_a.get_text(strip=True) if user_a else None,
                date=_icon_text(card, "fa-clock"),
                downloads=_int(_icon_text(card, "fa-download")),
                views=_int(_icon_text(card, "fa-eye")),
                favorites=_int(_icon_text(card, "fa-star")),
                url=f"{base_url}/material/{mid}",
            )
        )

    total = None
    m = re.search(r"共\s*(\d+)\s*条结果", soup.get_text(" ", strip=True))
    if m:
        total = int(m.group(1))

    return SearchPage(query=query, page=page, total=total, results=results)


def _field(text: str, label: str) -> str | None:
    """Value following a ``label:`` / ``label：`` in space-joined page text."""
    m = re.search(rf"{label}\s*[:：]\s*(\S+)", text)
    return m.group(1) if m else None


def parse_material(html: str, mid: int, base_url: str) -> Material:
    soup = _soup(html)
    flat = soup.get_text(" ", strip=True)

    h1 = soup.select_one("h1")
    course_a = soup.select_one('a[href^="/course/"]')
    dept_a = soup.select_one('a[href^="/department/"]')

    # Upload time has an embedded space ("2025-06-11 22:31") so it needs its
    # own pattern rather than the generic single-token _field().
    upm = re.search(r"上传时间\s*[:：]\s*([\d-]+\s+[\d:]+)", flat)
    favm = re.search(r"(\d+)\s*收藏", flat)

    return Material(
        id=mid,
        title=h1.get_text(strip=True) if h1 else None,
        type=_type_badge(soup),
        description=_material_description(soup),
        course=course_a.get_text(strip=True) if course_a else None,
        course_id=_id_from_href(course_a.get("href") if course_a else None, "course"),
        department=dept_a.get_text(strip=True) if dept_a else None,
        department_id=_id_from_href(dept_a.get("href") if dept_a else None, "department"),
        semester=_field(flat, "学期"),
        uploader=_field(flat, "上传者"),
        upload_time=upm.group(1) if upm else None,
        downloads=_int(_field(flat, "下载次数")),
        views=_int(_field(flat, "浏览次数")),
        favorites=int(favm.group(1)) if favm else None,
        file_type=_field(flat, "文件类型"),
        files=_material_files(soup),
        url=f"{base_url}/material/{mid}",
        download_url=f"{base_url}/download/{mid}",
    )


def parse_profile(html: str) -> Profile:
    """Parse the logged-in /profile page.

    The remaining-downloads figure is the server's authoritative quota — the
    page renders ``今日剩余下载次数`` followed by the count. Anchored on that
    label string (not the volatile Tailwind classes), like the other parsers;
    if the markup drifts, ``download_remaining`` falls to ``None`` and the
    fixture test in ``test_parsers.py`` flags it.
    """
    flat = _soup(html).get_text(" ", strip=True)
    m = re.search(r"今日剩余下载次数\s*(\d+)", flat)
    return Profile(download_remaining=int(m.group(1)) if m else None)


def _material_description(soup: BeautifulSoup) -> str | None:
    text = soup.get_text("\n", strip=True)
    m = re.search(
        r"资料描述\n(.+?)\n(?:压缩包文件结构|文件结构|资料评论|相关资料|举报|$)",
        text,
        re.S,
    )
    if not m:
        return None
    desc = m.group(1).strip()
    return desc or None


def _material_files(soup: BeautifulSoup) -> list[str]:
    heading = soup.find(string=re.compile("压缩包文件结构"))
    if heading is None:
        return []
    container = heading.find_parent(["div", "section"])
    if container is None:
        return []
    region = container.find_parent("div") or container
    files: list[str] = []
    for icon in region.select('i[class*="fa-file"]'):
        name = icon.parent.get_text(strip=True) if icon.parent else None
        if name:
            files.append(name)
    return files
