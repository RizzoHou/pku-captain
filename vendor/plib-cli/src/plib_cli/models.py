"""Dataclasses for the structured data plib-cli emits.

These are the JSON contract consumed by pku-captain's Tool wrapper (same
pattern as its ``pku3b`` JSON consumption). Field names are stable; add,
don't rename. (One deliberate pre-consumer exception: ``DownloadResult``'s
``quota_used``/``quota_limit`` became the single ``quota_remaining`` when the
quota source moved from a local counter to the server's /profile figure.)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SearchResult:
    """One material as it appears in a search-results card."""

    id: int
    title: str
    type: str | None
    description: str | None
    course: str | None
    department: str | None
    semester: str | None
    uploader: str | None
    date: str | None
    downloads: int | None
    views: int | None
    favorites: int | None
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchPage:
    """A page of search results plus pagination context."""

    query: str
    page: int
    total: int | None
    results: list[SearchResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "page": self.page,
            "total": self.total,
            "count": len(self.results),
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class Material:
    """Full detail for a single material (the /material/<id> page)."""

    id: int
    title: str
    type: str | None
    description: str | None
    course: str | None
    course_id: int | None
    department: str | None
    department_id: int | None
    semester: str | None
    uploader: str | None
    upload_time: str | None
    downloads: int | None
    views: int | None
    favorites: int | None
    file_type: str | None
    files: list[str] = field(default_factory=list)
    url: str = ""
    download_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Profile:
    """The logged-in account's /profile page (currently just the quota)."""

    download_remaining: int | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DownloadResult:
    """Outcome of a single download attempt.

    ``quota_remaining`` is the server's own ``今日剩余下载次数`` figure (read
    from /profile), decremented to reflect this download; ``None`` if the
    server quota could not be read.
    """

    id: int
    path: str
    filename: str
    bytes: int
    quota_remaining: int | None

    def to_dict(self) -> dict:
        return asdict(self)
