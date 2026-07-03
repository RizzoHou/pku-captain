"""教学网 (Blackboard) client: login, course/assignment/announcement crawl.

Split into pure parsers (HTML string -> data, unit-testable with fixtures) and a
:class:`BlackboardClient` that logs in and orchestrates the networked crawl.
Faithfully ports pku3b's ``api/blackboard.rs`` selectors and control flow.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable, TypeVar
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4 import NavigableString, Tag

from .cache import Cache
from .config import Credentials
from .dates import parse_deadline_iso, parse_posted_date
from .errors import AuthError, ParseError
from .http import HttpClient
from .ids import content_hash
from .iaaa import oauth_login, require_otp
from .models import Announcement, Assignment, Attachment

# -- endpoints (verbatim from pku3b) ---------------------------------------

OAUTH_REDIR = "http://course.pku.edu.cn/webapps/bb-sso-BBLEARN/execute/authValidate/campusLogin"
SSO_LOGIN = "https://course.pku.edu.cn/webapps/bb-sso-BBLEARN/execute/authValidate/campusLogin"
BB_HOME = "https://course.pku.edu.cn/webapps/portal/execute/tabs/tabAction"
BB_LOGIN = "https://course.pku.edu.cn/webapps/login/"
COURSE_INFO = "https://course.pku.edu.cn/webapps/blackboard/execute/announcement"
UPLOAD_ASSIGNMENT = "https://course.pku.edu.cn/webapps/assignment/uploadAssignment"
LIST_CONTENT = "https://course.pku.edu.cn/webapps/blackboard/content/listContent.jsp"
WEB_URL = "https://course.pku.edu.cn/"

# Course-menu entry labels whose hrefs become the assignment/announcement links.
_ASSIGNMENT_MENU_LABEL = "课程作业"
_ANNOUNCEMENT_MENU_LABEL = "课程通知"

_APPID = "blackboard"
_COURSE_KEY_RE = re.compile(r"key=([\d_]+),")
_CONTENT_BATCH = 8

T = TypeVar("T")
R = TypeVar("R")


class BlackboardUnauthorized(Exception):
    """Homepage redirected to the login page — the saved session is stale."""


# -- pure helpers -----------------------------------------------------------


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _collect_text(el: Tag) -> str:
    """Concatenate descendant text, skipping ``<script>`` (like pku3b)."""
    out: list[str] = []
    for node in el.children:
        if isinstance(node, NavigableString):
            if node.strip():
                out.append(str(node))
        elif isinstance(node, Tag):
            if node.name != "script":
                out.append(_collect_text(node))
    return "".join(out)


def _menu_url(menu: dict[str, str], label: str) -> str | None:
    """Absolutize a course-menu entry href, or ``None`` when absent."""
    href = menu.get(label)
    return urljoin(WEB_URL, href) if href else None


def _course_name(title: str) -> str:
    """Course name = title truncated at the last ASCII '(' (keeps 全角（）)."""
    idx = title.rfind("(")
    return title[:idx].strip() if idx >= 0 else title


def _course_title(long_title: str) -> str:
    """Title = substring after the first ASCII ':' in the anchor text."""
    head, sep, tail = long_title.partition(":")
    return tail.strip() if sep else long_title.strip()


@dataclass
class _ContentData:
    id: str
    title: str
    kind: str  # "assignment" | "document" | "announcement" | "unknown"
    has_link: bool
    descriptions: list[str] = field(default_factory=list)
    attachments: list[tuple[str, str]] = field(default_factory=list)
    time: str | None = None


def parse_courses(html: str) -> list[tuple[str, str, bool]]:
    """Return ``(course_key, long_title, is_current)`` for each listed course."""
    dom = _soup(html)
    courses: list[tuple[str, str, bool]] = []
    for portlet in dom.select("div.portlet"):
        title_el = portlet.select_one("span.moduleTitle")
        if title_el is None:
            continue
        title = title_el.get_text()
        if "课程" not in title and "Courses" not in title:
            continue
        is_current = "当前" in title or "Current Semester Courses" in title
        for ul in portlet.select("ul.courseListing"):
            for a in ul.select("li a"):
                href = a.get("href") or ""
                match = _COURSE_KEY_RE.search(href)
                if match is None:
                    continue
                courses.append((match.group(1), a.get_text(), is_current))
    return courses


def parse_course_menu(html: str) -> dict[str, str]:
    """Map course-menu entry text -> href (e.g. 课程作业 -> listContent url)."""
    dom = _soup(html)
    menu: dict[str, str] = {}
    for a in dom.select("#courseMenuPalette_contents > li > a"):
        href = a.get("href")
        if href:
            menu[a.get_text()] = href
    return menu


def _content_from_li(li: Tag) -> _ContentData | None:
    children = [c for c in li.children if isinstance(c, Tag)][:3]
    if len(children) < 3:
        return None
    img, title_div, detail_div = children

    alt = img.get("alt")
    if alt == "作业":
        kind = "assignment"
    elif alt in ("项目", "文件"):
        kind = "document"
    else:
        kind = "unknown"

    content_id = title_div.get("id")
    if not content_id:
        return None

    title = title_div.get_text().strip()
    has_link = title_div.find("a") is not None

    descriptions = [
        _collect_text(child).strip()
        for child in detail_div.select("div.vtbegenerated > *")
    ]

    attachments: list[tuple[str, str]] = []
    for a in detail_div.select("ul.attachments > li > a"):
        href = a.get("href") or ""
        text = a.get_text()
        if text.startswith(" "):
            text = text[1:]
        attachments.append((text, href))

    return _ContentData(
        id=content_id,
        title=title,
        kind=kind,
        has_link=has_link,
        descriptions=descriptions,
        attachments=attachments,
    )


def parse_content_list(html: str) -> list[_ContentData]:
    dom = _soup(html)
    out: list[_ContentData] = []
    for li in dom.select("#content_listContainer > li"):
        data = _content_from_li(li)
        if data is not None:
            out.append(data)
    return out


def parse_deadline_raw(html: str) -> str | None:
    dom = _soup(html)
    meta = dom.select_one("#assignMeta2")
    if meta is None:
        return None
    sibling = meta.find_next_sibling("div")
    if sibling is None:
        return None
    return " ".join(sibling.get_text().split())


def parse_attempt(html: str) -> str | None:
    dom = _soup(html)
    label = dom.select_one("h3#currentAttempt_label")
    if label is None:
        return None
    return " ".join(label.get_text().split())


def _compact(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def _announcement_dedup_key(title: str, content: str, time: str) -> str:
    title_c, content_c, time_c = _compact(title), _compact(content), _compact(time)
    if not content_c:
        return f"{title_c}|{time_c}"
    return f"{title_c}|{time_c}|{content_c}"


def parse_announcements(
    html: str, course_id: str, course_name: str
) -> list[_ContentData]:
    """Scrape announcements from a course page (pku3b's h3-block heuristic)."""
    dom = _soup(html)
    parsed: list[tuple[str, str, str]] = []  # (title, content, time)

    for container in dom.select(
        ".vtbegenerated, #content_listContainer, div.content, div.clearfix"
    ):
        h3s = container.find_all("h3")
        if h3s:
            for h3 in h3s:
                title = h3.get_text().strip()
                if (
                    not title
                    or "课程" in title
                    or "学期" in title
                    or title == "我的小组"
                    or title == "公告"
                    or "查看选项" in title
                    or "菜单管理" in title
                ):
                    continue
                # Blackboard nests the 发布时间/发帖者/发布至 metadata inside
                # <div> siblings of the <h3> (not a direct <p> as pku3b's
                # narrower check assumed), so match on the text, not the tag,
                # and keep the metadata out of the body.
                content_parts: list[str] = []
                time = ""
                seen = 0
                for sib in h3.next_siblings:
                    if seen >= 12:
                        break
                    if not isinstance(sib, Tag):
                        continue
                    seen += 1
                    if sib.name == "h3":
                        break
                    text = sib.get_text()
                    stripped = text.strip()
                    if not stripped:
                        continue
                    if "发布时间" in text:
                        if not time:
                            time = stripped
                        continue
                    if stripped.startswith("发帖者") or stripped.startswith("发布至"):
                        continue
                    content_parts.append(text)
                content = "\n".join(content_parts)
                parsed.append((title, content, time))
        else:
            content = container.get_text().strip()
            p = container.find("p")
            time = p.get_text().strip() if p is not None else ""
            lower = content.lower()
            if "var json" in lower or "查看选项" in lower or "菜单管理" in lower:
                continue
            if content and len(content) > 10:
                chars = list(content)
                title = "".join(chars[:20])
                if len(chars) > 20:
                    title = f"{title}..."
                parsed.append((title, content, time))

    out: list[_ContentData] = []
    seen_keys: set[str] = set()
    for idx, (title, content, time) in enumerate(parsed):
        if not title or len(title) < 5:
            continue
        if title.startswith(course_name) or "学期" in title or title == "公告":
            continue
        content_clean = content.strip()
        if content_clean.startswith(course_name) and len(content_clean) < 50:
            continue
        dedup_key = f"{course_id}:{_announcement_dedup_key(title, content, time)}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        descriptions = (
            [line.strip() for line in content.splitlines() if line.strip()]
            if content
            else []
        )
        out.append(
            _ContentData(
                id=f"{course_id}_{idx}",
                title=title,
                kind="announcement",
                has_link=False,
                descriptions=descriptions,
                attachments=[],
                time=time or None,
            )
        )
    return out


def _map_concurrent(
    fn: Callable[[T], R], items: Iterable[T], *, workers: int
) -> list[R]:
    items = list(items)
    if not items:
        return []
    if workers <= 1 or len(items) == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


# -- networked client -------------------------------------------------------


class BlackboardClient:
    def __init__(
        self,
        http: HttpClient,
        cache: Cache,
        *,
        workers: int = 8,
    ) -> None:
        self.http = http
        self.cache = cache
        self.workers = workers
        self._coursepage_html: dict[str, str] = {}

    # -- auth ---------------------------------------------------------------

    def login(self, creds: Credentials, otp_code: str = "") -> None:
        """Ensure an authenticated session, reusing saved cookies when valid."""
        try:
            self._fetch_homepage()
            return  # saved session still valid
        except BlackboardUnauthorized:
            pass
        self._do_login(creds, otp_code)
        self.http.save_cookies()

    def _do_login(self, creds: Credentials, otp_code: str) -> None:
        require_otp(self.http, _APPID, creds.username)  # observed, non-blocking
        token = oauth_login(
            self.http,
            appid=_APPID,
            username=creds.username,
            password=creds.password,
            otp_code=otp_code,
            redir=OAUTH_REDIR,
        )
        res = self.http.get(
            SSO_LOGIN, params={"_rand": "0.0", "token": token}, allow_redirects=True
        )
        if not res.ok:
            raise AuthError(f"blackboard SSO login failed: HTTP {res.status_code}")

    def _fetch_homepage(self) -> str:
        res = self.http.get(
            BB_HOME, params={"tab_tab_group_id": "_1_1"}, allow_redirects=False
        )
        if 300 <= res.status_code < 400:
            location = res.headers.get("Location", "")
            if "/webapps/login" in location or location.rstrip("/") == BB_LOGIN.rstrip("/"):
                raise BlackboardUnauthorized()
            res = self.http.get(location, allow_redirects=True)
        if not res.ok:
            raise BlackboardUnauthorized()
        return res.text

    # -- courses ------------------------------------------------------------

    def get_courses(
        self, *, only_current: bool, force: bool
    ) -> list[tuple[str, str, bool]]:
        courses = self.cache.get_or_compute(
            "Blackboard::courses",
            lambda: parse_courses(self._fetch_homepage()),
            force=force,
        )
        courses = [tuple(c) for c in courses]  # JSON round-trip -> lists
        if not courses:
            raise ParseError("no courses found on the Blackboard homepage")
        if only_current:
            courses = [c for c in courses if c[2]]
        return courses

    def _get_coursepage(self, course_id: str) -> str:
        html = self._coursepage_html.get(course_id)
        if html is None:
            res = self.http.get(
                COURSE_INFO,
                params={
                    "method": "search",
                    "context": "course_entry",
                    "course_id": course_id,
                    "handle": "announcements_entry",
                    "mode": "view",
                },
            )
            if not res.ok:
                raise ParseError(f"course page {course_id}: HTTP {res.status_code}")
            html = res.text
            self._coursepage_html[course_id] = html
        return html

    # -- assignments --------------------------------------------------------

    def list_assignments(
        self,
        *,
        include_completed: bool,
        only_current: bool,
        force: bool,
    ) -> list[Assignment]:
        courses = self.get_courses(only_current=only_current, force=force)
        results: list[Assignment] = []
        for course_id, long_title, _is_current in courses:
            results.extend(
                self._course_assignments(course_id, long_title, force=force)
            )
        # unfinished-only unless include_completed; then sort by deadline (None first)
        if not include_completed:
            results = [a for a in results if not a.completed]
        results.sort(key=lambda a: (a.deadline_iso is not None, a.deadline_iso or ""))
        return results

    def _course_assignments(
        self, course_id: str, long_title: str, *, force: bool
    ) -> list[Assignment]:
        title = _course_title(long_title)
        name = _course_name(title)

        menu = self._menu(course_id, force=force)
        course_url = _menu_url(menu, _ASSIGNMENT_MENU_LABEL)
        seed_ids = _seed_content_ids(menu)

        contents = self.cache.get_or_compute(
            f"contents_{course_id}",
            lambda: [c.__dict__ for c in self._crawl_contents(course_id, seed_ids)],
            force=force,
        )
        assignment_contents = [
            c for c in contents if c.get("kind") == "assignment"
        ]

        def build(content: dict) -> Assignment:
            data = self.cache.get_or_compute(
                f"assignment_{course_id}_{content['id']}",
                lambda: self._fetch_assignment_data(course_id, content["id"]),
                force=force,
            )
            deadline_raw = data.get("deadline")
            attempt = data.get("attempt")
            return Assignment(
                id=content_hash(course_id, content["id"]),
                course_name=name,
                course_title=title,
                course_id=course_id,
                title=content["title"],
                deadline_raw=deadline_raw,
                deadline_iso=parse_deadline_iso(deadline_raw),
                completed=attempt is not None,
                last_attempt=attempt,
                descriptions=list(content.get("descriptions") or []),
                attachments=[
                    Attachment(name=a[0], uri=a[1])
                    for a in (content.get("attachments") or [])
                ],
                content_id=content["id"],
                course_url=course_url,
            )

        return _map_concurrent(build, assignment_contents, workers=self.workers)

    def _menu(self, course_id: str, *, force: bool) -> dict[str, str]:
        return self.cache.get_or_compute(
            f"menu_{course_id}",
            lambda: parse_course_menu(self._get_coursepage(course_id)),
            force=force,
        )

    def _crawl_contents(self, course_id: str, seed_ids: list[str]) -> list[_ContentData]:
        visited: set[str] = set(seed_ids)
        probe: list[str] = list(visited)
        results: list[_ContentData] = []
        while probe:
            batch = probe[-_CONTENT_BATCH:]
            del probe[-_CONTENT_BATCH:]
            pages = _map_concurrent(
                lambda cid: self._fetch_content_page(course_id, cid),
                batch,
                workers=self.workers,
            )
            for html in pages:
                if html is None:
                    continue
                for data in parse_content_list(html):
                    if data.id in visited:
                        continue
                    visited.add(data.id)
                    results.append(data)
                    if data.has_link:
                        probe.append(data.id)
        return results

    def _fetch_content_page(self, course_id: str, content_id: str) -> str | None:
        res = self.http.get(
            LIST_CONTENT,
            params={"content_id": content_id, "course_id": course_id},
        )
        return res.text if res.ok else None

    def _fetch_assignment_data(self, course_id: str, content_id: str) -> dict:
        upload = self.http.get(
            UPLOAD_ASSIGNMENT,
            params={
                "action": "newAttempt",
                "content_id": content_id,
                "course_id": course_id,
            },
        )
        deadline = parse_deadline_raw(upload.text) if upload.ok else None
        view = self.http.get(
            UPLOAD_ASSIGNMENT,
            params={
                "mode": "view",
                "content_id": content_id,
                "course_id": course_id,
            },
        )
        attempt = parse_attempt(view.text) if view.ok else None
        return {"deadline": deadline, "attempt": attempt}

    # -- announcements ------------------------------------------------------

    def list_announcements(
        self, *, only_current: bool, force: bool
    ) -> list[Announcement]:
        courses = self.get_courses(only_current=only_current, force=force)
        collected: list[tuple[str, str | None, _ContentData]] = []
        for course_id, long_title, _is_current in courses:
            name = _course_name(_course_title(long_title))
            course_url = _menu_url(self._menu(course_id, force=force), _ANNOUNCEMENT_MENU_LABEL)
            raw = self.cache.get_or_compute(
                f"announcements_{course_id}",
                lambda cid=course_id, nm=name: [
                    c.__dict__
                    for c in parse_announcements(self._get_coursepage(cid), cid, nm)
                ],
                force=force,
            )
            for record in raw:
                collected.append((name, course_url, _content_from_dict(record)))

        # newest first: items with a time before those without (pku3b sort).
        collected.sort(key=lambda triple: triple[2].time or "", reverse=True)

        announcements: list[Announcement] = []
        for index, (name, course_url, content) in enumerate(collected, start=1):
            course_id = content.id.rsplit("_", 1)[0]
            announcements.append(
                Announcement(
                    id=content_hash(course_id, content.id),
                    index=index,
                    course=name,
                    course_id=course_id,
                    title=content.title,
                    posted_time=content.time,
                    posted_date=parse_posted_date(content.time),
                    body="\n".join(content.descriptions),
                    descriptions=list(content.descriptions),
                    attachments=[
                        Attachment(name=a[0], uri=a[1]) for a in content.attachments
                    ],
                    course_url=course_url,
                )
            )
        return announcements


def _seed_content_ids(menu: dict[str, str]) -> list[str]:
    """Course-menu hrefs that point at listContent.jsp -> seed content ids."""
    seeds: list[str] = []
    for href in menu.values():
        parsed = urlparse(href)
        if not LIST_CONTENT.endswith(parsed.path):
            continue
        content_ids = parse_qs(parsed.query).get("content_id")
        if content_ids:
            seeds.append(content_ids[0])
    return seeds


def _content_from_dict(record: dict) -> _ContentData:
    return _ContentData(
        id=record["id"],
        title=record["title"],
        kind=record.get("kind", "unknown"),
        has_link=bool(record.get("has_link", False)),
        descriptions=list(record.get("descriptions") or []),
        attachments=[tuple(a) for a in (record.get("attachments") or [])],
        time=record.get("time"),
    )
