"""HTML parsers for each dean.pku.edu.cn page type.

Selectors target stable CSS classes observed on the live site:

* sidebar      — ``.student_nav li`` with ``p.tosubnav`` category headers
* rules list   — ``#sub_content`` anchors to ``rules_info.php?id=``
* rule detail  — ``.newsinfo_box`` body text
* file listing — ``.load_item`` rows (download.php / openinfo.php)
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .client import INDEX_URL, WEB_URL
from .errors import DeanError
from .models import (
    FileItem,
    GuideDoc,
    GuideSection,
    NoticeDoc,
    NoticeItem,
    Page,
    RelatedLink,
    RuleDoc,
    RuleItem,
    SidebarLink,
)
from .pagination import parse_last_page

_ID_RE = re.compile(r"[?&]id=(\d+)")
_DIGITS_RE = re.compile(r"(\d+)")
_UPDATE_RE = re.compile(r"更新日期[：:]\s*([0-9-]+)")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Related-link target page -> group label.
_RELATED_GROUPS = (
    ("rules_info.php", "policy"),
    ("notice_details.php", "notice"),
    ("download_down.php", "download"),
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _extract_id(href: str) -> int | None:
    m = _ID_RE.search(href or "")
    return int(m.group(1)) if m else None


# -- sidebar ----------------------------------------------------------------


def parse_sidebar(html: str) -> list[SidebarLink]:
    """Parse the 学生 sidebar from index.php into categorized links."""
    soup = _soup(html)
    nav = soup.select_one(".student_nav")
    if nav is None:
        raise DeanError("student sidebar not found on index page", code="parse_error")

    links: list[SidebarLink] = []
    for li in nav.find_all("li", recursive=True):
        header = li.find("p", class_="tosubnav")
        category = header.get_text(strip=True) if header else ""
        sub = li.find("div", class_="sub_stunav")
        if sub is not None:
            anchors = sub.find_all("a")
        else:
            # Top-level entry (e.g. 学生服务中心): the <li>'s own anchor.
            anchors = li.find_all("a", recursive=False)
        for a in anchors:
            href = a.get("href")
            title = a.get_text(strip=True)
            if not href or not title:
                continue
            links.append(
                SidebarLink(
                    category=category or title,
                    title=title,
                    url=urljoin(INDEX_URL, href),
                )
            )
    if not links:
        raise DeanError("no links found in student sidebar", code="parse_error")
    return links


# -- rules listings ---------------------------------------------------------


def parse_rules(html: str, scope: str) -> Page:
    """Parse rules.php / rules_school.php into a page of :class:`RuleItem`."""
    soup = _soup(html)
    content = soup.select_one("#sub_content") or soup
    seen: set[int] = set()
    items: list[RuleItem] = []
    for a in content.select('a[href*="rules_info.php"]'):
        rid = _extract_id(a.get("href", ""))
        title = a.get_text(strip=True)
        if rid is None or not title or rid in seen:
            continue
        seen.add(rid)
        items.append(
            RuleItem(
                id=rid,
                title=title,
                scope=scope,
                url=urljoin(WEB_URL, a["href"]),
            )
        )
    return Page(page=_current_page(soup), last_page=parse_last_page(soup), items=items)


def parse_rule_doc(html: str, rule_id: int, url: str) -> RuleDoc:
    """Parse a single rule detail page (rules_info.php?id=...)."""
    soup = _soup(html)
    box = soup.select_one(".newsinfo_box") or soup.select_one(".news_con")
    if box is None:
        raise DeanError(f"rule body not found for id={rule_id}", code="parse_error")
    title_el = soup.select_one("#sub_content .active") or box.find(["h1", "h2", "h3"])
    title = title_el.get_text(strip=True) if title_el else ""
    text = box.get_text("\n", strip=True)
    # A missing rule still serves the template with an empty breadcrumb and a
    # body holding only the share widget — treat that as not found.
    if not title and len(text) < 10:
        raise DeanError(f"no rule found with id={rule_id}", code="not_found")
    return RuleDoc(id=rule_id, title=title, text=text, url=url)


# -- notices ----------------------------------------------------------------


def parse_notices(html: str) -> Page:
    """Parse notice.php into a page of :class:`NoticeItem`."""
    soup = _soup(html)
    items: list[NoticeItem] = []
    seen: set[int] = set()
    for box in soup.select(".notice_item"):
        link = box.select_one('a[href*="notice_details.php"]')
        if link is None:
            continue
        nid = _extract_id(link.get("href", ""))
        title = link.get_text(strip=True)
        if nid is None or not title or nid in seen:
            continue
        seen.add(nid)
        date_el = box.find("span")
        date = date_el.get_text(strip=True) if date_el else ""
        items.append(
            NoticeItem(
                id=nid,
                title=title,
                url=urljoin(WEB_URL, link["href"]),
                date=date if _DATE_RE.fullmatch(date) else None,
            )
        )
    return Page(page=_current_page(soup), last_page=parse_last_page(soup), items=items)


def parse_notice_doc(html: str, notice_id: int, url: str) -> NoticeDoc:
    """Parse a single notice detail page (notice_details.php?id=...)."""
    soup = _soup(html)
    box = soup.select_one(".newsinfo_box") or soup.select_one(".news_con")
    if box is None:
        raise DeanError(f"notice body not found for id={notice_id}", code="parse_error")

    title_el = box.find("h1") or soup.select_one("#sub_content .active")
    title = title_el.get_text(strip=True) if title_el else ""

    date_el = box.find("span", recursive=False)
    raw_date = date_el.get_text(strip=True) if date_el else ""
    date = raw_date if _DATE_RE.fullmatch(raw_date) and raw_date != "1970-01-01" else None

    # Drop the heading, the date span, and the share widget before reading body,
    # so a missing notice (which serves only those) is detectably empty.
    for junk in (box.find("h1"), date_el, *box.select(".share_ds, .bdsharebuttonbox")):
        if junk is not None:
            junk.decompose()
    text = box.get_text("\n", strip=True)

    if not title and not text:
        raise DeanError(f"no notice found with id={notice_id}", code="not_found")
    return NoticeDoc(id=notice_id, title=title, text=text, url=url, date=date)


# -- student guide ----------------------------------------------------------


def parse_guide(html: str, guide_id: int, url: str) -> GuideDoc:
    """Parse a student guide page (student_info.php?id=...).

    Layout: ``.main_con`` holds an ``h1`` title, then alternating ``.item``
    (an ``h2`` heading) and ``.list`` (its body) blocks, a ``.share_ds`` with the
    update date, and a ``.tab_info`` of related policy/notice/download links.
    """
    soup = _soup(html)
    main = soup.select_one(".main_con")
    if main is None:
        # A missing id returns HTTP 200 with an essentially empty body.
        raise DeanError(f"no guide found with id={guide_id}", code="not_found")

    title_el = main.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    sections: list[GuideSection] = []
    for item in main.find_all("div", class_="item", recursive=False):
        heading_el = item.find(["h2", "h3"])
        heading = heading_el.get_text(strip=True) if heading_el else ""
        body_el = item.find_next_sibling("div", class_="list")
        body = body_el.get_text("\n", strip=True) if body_el else ""
        if heading or body:
            sections.append(GuideSection(heading=heading, body=body))

    if not title and not sections:
        raise DeanError(f"no guide found with id={guide_id}", code="not_found")

    update_match = _UPDATE_RE.search(main.get_text())
    update_date = update_match.group(1) if update_match else None

    related: list[RelatedLink] = []
    seen: set[tuple[str, str]] = set()
    for a in main.select(".tab_info a[href]"):
        href = a["href"]
        text = a.get_text(strip=True)
        if not text:
            continue
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        related.append(
            RelatedLink(group=_related_group(href), title=text, url=urljoin(WEB_URL, href))
        )

    return GuideDoc(
        id=guide_id,
        title=title,
        url=url,
        update_date=update_date,
        sections=sections,
        related=related,
    )


def _related_group(href: str) -> str:
    for needle, group in _RELATED_GROUPS:
        if needle in href:
            return group
    return "other"


# -- file listings ----------------------------------------------------------


def parse_files(html: str, kind: str) -> Page:
    """Parse download.php / openinfo.php into a page of :class:`FileItem`."""
    soup = _soup(html)
    items: list[FileItem] = []
    for item in soup.select(".load_item"):
        title_el = item.select_one(".load_top")
        link = item.select_one("a.xz") or item.select_one('a[href*="download_down.php"]')
        if title_el is None or link is None:
            continue
        href = link.get("href", "")
        fid = _extract_id(href)
        if fid is None:
            continue
        num_el = item.select_one("a.num")
        date_el = item.select_one("a.update")
        items.append(
            FileItem(
                id=fid,
                title=title_el.get_text(strip=True),
                kind=kind,
                download_url=urljoin(WEB_URL, href),
                downloads=_first_int(num_el.get_text()) if num_el else None,
                date=_after_colon(date_el.get_text()) if date_el else None,
            )
        )
    return Page(page=_current_page(soup), last_page=parse_last_page(soup), items=items)


# -- helpers ----------------------------------------------------------------


def _current_page(soup: BeautifulSoup) -> int:
    active = soup.select_one("#page_bar a.active")
    if active:
        m = re.search(r"[?&]page=(\d+)", active.get("href", ""))
        if m:
            return int(m.group(1))
    return 1


def _first_int(text: str) -> int | None:
    m = _DIGITS_RE.search(text or "")
    return int(m.group(1)) if m else None


def _after_colon(text: str) -> str | None:
    if not text:
        return None
    return text.split("：", 1)[-1].split(":", 1)[-1].strip() or None
