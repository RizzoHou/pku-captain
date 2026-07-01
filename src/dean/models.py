"""Plain dataclasses for the resources the CLI returns.

Every model is JSON-serializable via :func:`dataclasses.asdict`; the CLI puts
these dicts straight into the envelope's ``data`` field.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SidebarLink:
    """One entry in the index page's 学生 (student) sidebar."""

    category: str
    title: str
    url: str


@dataclass
class RuleItem:
    """A rule/regulation listed on rules.php or rules_school.php."""

    id: int
    title: str
    scope: str  # "school" | "national"
    url: str


@dataclass
class RuleDoc:
    """Full text of a single rule (rules_info.php?id=...)."""

    id: int
    title: str
    text: str
    url: str


@dataclass
class GuideSection:
    """One heading/body section of a student guide page."""

    heading: str
    body: str


@dataclass
class RelatedLink:
    """A cross-reference shown on a guide page (policy / notice / download)."""

    group: str  # "policy" | "notice" | "download" | "other"
    title: str
    url: str


@dataclass
class GuideDoc:
    """A student guide page (student_info.php?id=...)."""

    id: int
    title: str
    url: str
    update_date: str | None = None
    sections: list = field(default_factory=list)
    related: list = field(default_factory=list)


@dataclass
class NoticeItem:
    """A notice/announcement listed on notice.php."""

    id: int
    title: str
    url: str
    date: str | None = None


@dataclass
class NoticeDoc:
    """Full text of a single notice (notice_details.php?id=...)."""

    id: int
    title: str
    text: str
    url: str
    date: str | None = None


@dataclass
class FileItem:
    """A downloadable file on download.php or openinfo.php."""

    id: int
    title: str
    kind: str  # "download" | "openinfo"
    download_url: str
    downloads: int | None = None
    date: str | None = None


@dataclass
class Page:
    """One page of a paginated listing."""

    page: int
    last_page: int
    items: list = field(default_factory=list)
