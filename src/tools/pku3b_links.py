"""Best-effort Teaching Web link resolver for pku3b data.

The pku3b CLI currently returns clean assignment/announcement records but not
their original Blackboard URLs. Its local cache does include enough public
course-menu/content data to recover useful entry links, so this module keeps
that brittle cache probing isolated from the rest of the app.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

PKU3B_WEB_URL = "https://course.pku.edu.cn/"
_DEFAULT_CACHE_DIR = Path.home() / "Library" / "Caches" / "org.sshwy.pku3b"
_COURSE_ID = re.compile(r"course_id=([^&]+)")


class Pku3bLinkResolver:
    """Resolve course and content links from pku3b's local cache."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
        self._menu_by_course: dict[str, dict[str, str]] | None = None
        self._course_id_by_name: dict[str, str] | None = None
        self._content_id_by_title: dict[str, str] | None = None

    def assignment_links(
        self, *, course_id: str | None, title: str | None
    ) -> dict[str, str]:
        links: dict[str, str] = {}
        course_id = (course_id or "").strip()
        title = (title or "").strip()
        if not course_id:
            return links

        assignment_url = self.course_menu_url(course_id, "课程作业")
        if assignment_url:
            links["url"] = assignment_url

        raw_content_id = self.content_id_for_title(title)
        if raw_content_id:
            links["blackboard_content_id"] = raw_content_id
            links["submit_url"] = _assignment_submit_url(course_id, raw_content_id)
        return links

    def announcement_url(
        self, *, course: str | None = None, course_id: str | None = None
    ) -> str | None:
        resolved_course_id = (course_id or "").strip()
        if not resolved_course_id:
            resolved_course_id = self.course_id_for_name(course or "") or ""
        if not resolved_course_id:
            return None
        return self.course_menu_url(resolved_course_id, "课程通知")

    def course_menu_url(self, course_id: str, label: str) -> str | None:
        menu = self._menus().get(course_id)
        if not menu:
            return None
        return menu.get(label)

    def course_id_for_name(self, course_name: str) -> str | None:
        needle = _normalize_course_name(course_name)
        if not needle:
            return None
        courses = self._courses()
        exact = courses.get(needle)
        if exact:
            return exact
        for name, course_id in courses.items():
            if needle in name or name in needle:
                return course_id
        return None

    def content_id_for_title(self, title: str) -> str | None:
        normalized = _normalize_title(title)
        if not normalized:
            return None
        return self._content_ids().get(normalized)

    def _menus(self) -> dict[str, dict[str, str]]:
        if self._menu_by_course is not None:
            return self._menu_by_course
        menus: dict[str, dict[str, str]] = {}
        for data in self._cache_json_values():
            if not isinstance(data, dict):
                continue
            normalized_menu: dict[str, str] = {}
            course_id = ""
            for label, value in data.items():
                if not isinstance(label, str) or not isinstance(value, str):
                    continue
                if "course_id=" not in value:
                    continue
                course_id = course_id or _course_id_from_url(value)
                normalized_menu[label] = _absolute_url(value)
            if course_id and normalized_menu:
                menus[course_id] = normalized_menu
        self._menu_by_course = menus
        return menus

    def _courses(self) -> dict[str, str]:
        if self._course_id_by_name is not None:
            return self._course_id_by_name
        courses: dict[str, str] = {}
        for data in self._cache_json_values():
            if not isinstance(data, list):
                continue
            for item in data:
                if not _looks_like_course_tuple(item):
                    continue
                course_id, raw_title = str(item[0]), str(item[1])
                name = _normalize_course_name(_course_name_from_title(raw_title))
                if name and course_id:
                    courses.setdefault(name, course_id)
        self._course_id_by_name = courses
        return courses

    def _content_ids(self) -> dict[str, str]:
        if self._content_id_by_title is not None:
            return self._content_id_by_title
        content_ids: dict[str, str] = {}
        for data in self._cache_json_values():
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("id")
                title = item.get("title")
                if not isinstance(raw_id, str) or not isinstance(title, str):
                    continue
                if not raw_id.startswith("_"):
                    continue
                normalized = _normalize_title(title)
                if normalized:
                    content_ids.setdefault(normalized, raw_id)
        self._content_id_by_title = content_ids
        return content_ids

    def _cache_json_values(self) -> list[Any]:
        if not self.cache_dir.exists():
            return []
        values: list[Any] = []
        for path in self.cache_dir.iterdir():
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
                values.append(json.loads(text))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        return values


def enrich_assignments(
    assignments: list[dict[str, Any]], resolver: Pku3bLinkResolver | None = None
) -> list[dict[str, Any]]:
    resolver = resolver or Pku3bLinkResolver()
    enriched: list[dict[str, Any]] = []
    for assignment in assignments:
        item = dict(assignment)
        item.update(
            resolver.assignment_links(
                course_id=str(item.get("course_id") or ""),
                title=str(item.get("title") or ""),
            )
        )
        enriched.append(item)
    return enriched


def enrich_announcements(
    announcements: list[dict[str, Any]], resolver: Pku3bLinkResolver | None = None
) -> list[dict[str, Any]]:
    resolver = resolver or Pku3bLinkResolver()
    enriched: list[dict[str, Any]] = []
    for announcement in announcements:
        item = dict(announcement)
        url = resolver.announcement_url(
            course=str(item.get("course") or ""),
            course_id=str(item.get("course_id") or ""),
        )
        if url:
            item["url"] = url
        enriched.append(item)
    return enriched


def _assignment_submit_url(course_id: str, content_id: str) -> str:
    query = urlencode(
        {
            "content_id": content_id,
            "course_id": course_id,
            "group_id": "",
            "mode": "view",
        }
    )
    return urljoin(PKU3B_WEB_URL, f"/webapps/assignment/uploadAssignment?{query}")


def _absolute_url(value: str) -> str:
    return urljoin(PKU3B_WEB_URL, value)


def _course_id_from_url(value: str) -> str:
    parsed = urlparse(_absolute_url(value))
    query = parse_qs(parsed.query)
    values = query.get("course_id")
    if values:
        return values[0]
    match = _COURSE_ID.search(value)
    return match.group(1) if match else ""


def _course_name_from_title(raw_title: str) -> str:
    title = raw_title.split(":", 1)[-1]
    return re.sub(r"\([^)]*学期\)\s*$", "", title).strip()


def _looks_like_course_tuple(item: object) -> bool:
    return (
        isinstance(item, list)
        and len(item) >= 2
        and isinstance(item[0], str)
        and item[0].startswith("_")
        and isinstance(item[1], str)
    )


def _normalize_course_name(value: str) -> str:
    text = re.sub(r"\([^)]*\)", "", value)
    return re.sub(r"\s+", "", text).casefold()


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
