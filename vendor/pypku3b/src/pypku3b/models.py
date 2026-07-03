"""Return-value dataclasses for the pypku3b client.

Each carries a ``to_dict()`` that emits JSON-friendly plain dicts. The
``Assignment`` and ``Identity`` dict shapes intentionally match pku3b's
``assignment list --format json`` / ``identity --format json`` output key-for-key
(and key order) so a consumer that parsed the CLI JSON keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attachment:
    name: str
    uri: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "uri": self.uri}


@dataclass
class Assignment:
    id: str
    course_name: str
    course_title: str
    course_id: str
    title: str
    deadline_raw: str | None
    deadline_iso: str | None
    completed: bool
    last_attempt: str | None
    descriptions: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    # Blackboard-native link data (not in pku3b's JSON; kept off ``to_dict`` so
    # the CLI stays byte-compatible). A host app can build submit/entry URLs
    # from these without probing pku3b's on-disk cache.
    content_id: str = ""
    course_url: str | None = None

    def to_dict(self) -> dict:
        # Key order mirrors pku3b's JsonAssignment for drop-in compatibility.
        return {
            "id": self.id,
            "course_name": self.course_name,
            "course_title": self.course_title,
            "course_id": self.course_id,
            "title": self.title,
            "deadline_raw": self.deadline_raw,
            "deadline_iso": self.deadline_iso,
            "completed": self.completed,
            "last_attempt": self.last_attempt,
            "descriptions": list(self.descriptions),
            "attachments": [a.to_dict() for a in self.attachments],
        }


@dataclass
class Announcement:
    """One course announcement.

    Unlike pku3b's ``announcement list`` (which is text-only and carries no
    date), the in-process client returns the posted time inline — it is scraped
    from the same course page — so no separate detail fetch is needed to resolve
    a date. ``index`` is the 1-based position in the sorted list.
    """

    id: str
    index: int
    course: str
    course_id: str
    title: str
    posted_time: str | None = None
    posted_date: str | None = None
    body: str = ""
    descriptions: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    # The course 课程通知 entry URL (for a clickable link); off ``to_dict``.
    course_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "index": self.index,
            "course": self.course,
            "course_id": self.course_id,
            "title": self.title,
            "posted_time": self.posted_time,
            "posted_date": self.posted_date,
            "body": self.body,
            "descriptions": list(self.descriptions),
            "attachments": [a.to_dict() for a in self.attachments],
        }


# Field order matches pku3b's identity `--format json` object.
_IDENTITY_FIELDS = (
    "name",
    "student_id",
    "sex",
    "user_identity",
    "department",
    "student_type",
    "speciality",
    "direction",
    "politics",
    "ethnic",
    "native_place",
)


@dataclass
class Identity:
    name: str | None = None
    student_id: str | None = None
    sex: str | None = None
    user_identity: str | None = None
    department: str | None = None
    student_type: str | None = None
    speciality: str | None = None
    direction: str | None = None
    politics: str | None = None
    ethnic: str | None = None
    native_place: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {name: getattr(self, name) for name in _IDENTITY_FIELDS}


@dataclass
class CourseTable:
    """The personal course table.

    ``raw`` is the portal's ``getCourseInfo.do`` payload parsed from JSON (the
    same structure ``coursetable --raw`` prints); ``term`` is the resolved
    ``xndxq`` academic-year-term string.
    """

    term: str | None
    raw: dict

    def to_dict(self) -> dict:
        return {"term": self.term, "raw": self.raw}
