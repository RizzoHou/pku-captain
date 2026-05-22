"""PKU3bAnnouncementsTool — fetch course announcements via the ``pku3b`` CLI.

Counterpart of :class:`~src.tools.pku3b_assignments.PKU3bAssignmentsTool`.
Unlike ``assignment list``, the ``announcement`` subcommand does **not**
support ``--format json`` (even on our fork, as of pku3b 0.13.0), so this
tool runs the plain-text ``announcement list`` / ``announcement show``
output through :func:`~src.tools.pku3b.strip_ansi` and parses it. See the
"Implementation notes" section of ``docs/tasks/006_pku3b_announcements_tool.md``.

Two modes:

* No ``announcement_id`` — list mode: parses ``announcement list`` into a
  structured list of ``{index, course, title, id}`` records. List titles
  are truncated by ``pku3b`` itself; fetch a single announcement's full
  title and body with detail mode.
* ``announcement_id`` given — detail mode: parses ``announcement show <id>``
  into a single record with the full title, posted time, and body text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_EXECUTABLE,
    DEFAULT_TIMEOUT,
    Pku3bNotFoundError,
    Pku3bTimeoutError,
    run_pku3b,
)

# A list entry begins with a bracketed 1-based index at the start of a line,
# e.g. "[ 12] ". Announcement titles may themselves contain newlines, so an
# entry can span several physical lines — split on these markers, not on "\n".
_ENTRY_START = re.compile(r"^\[\s*(\d+)\]", re.MULTILINE)
# pku3b IDs are lowercase hex; leading zeros are dropped so the length varies.
_TRAILING_ID = re.compile(r"\s([0-9a-f]{8,})\s*$")
# Header line of `announcement list`, e.g. "> 课程公告 (84) <".
_LIST_HEADER = re.compile(r"课程公告\s*\((\d+)\)")
# "ID: <hex>" line in `announcement show` output.
_DETAIL_ID = re.compile(r"^ID:\s*([0-9a-f]{8,})\s*$", re.MULTILINE)
# "发布时间: ..." line in `announcement show` output.
_POSTED_AT = re.compile(r"^发布时间[:：]\s*(.+)$", re.MULTILINE)

_SEPARATOR = " > "


@dataclass
class Announcement:
    """One row of ``announcement list`` — title is truncated by pku3b."""

    index: int
    course: str
    title: str
    id: str


@dataclass
class AnnouncementDetail:
    """One ``announcement show`` result — full title and body."""

    id: str
    course: str
    title: str
    posted_at: str | None
    body: str


class PKU3bAnnouncementsTool(Tool):
    name: ClassVar[str] = "pku3b_announcements"
    description: ClassVar[str] = (
        "List course announcements (公告/通知) from PKU 教学网 (Blackboard) "
        "via the local `pku3b` CLI. With no arguments, returns every "
        "announcement's course, (truncated) title, and id. Pass "
        "`announcement_id` to fetch one announcement's full title, posted "
        "time, and body text. Pass `course` to filter the list to a course "
        "by name substring. Use this to answer questions like "
        "“有什么课程公告？” / “程设最近发了什么通知？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "announcement_id": {
                "type": "string",
                "description": (
                    "If set, fetch the full detail of a single announcement "
                    "by its id (from a prior list call) instead of listing."
                ),
            },
            "course": {
                "type": "string",
                "description": (
                    "List mode only: keep only announcements whose course "
                    "name contains this substring (case-insensitive)."
                ),
            },
            "all_term": {
                "type": "boolean",
                "description": (
                    "Include announcements from all terms, not just the "
                    "current one (passes --all-term to pku3b). Default: false."
                ),
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": (
                    "List mode only: cap the number of announcements "
                    "returned (after filtering). Omit for no cap."
                ),
                "minimum": 1,
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Force pku3b to refresh from the server instead of "
                    "using its cache (passes -f). Default: false."
                ),
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.executable = executable
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        announcement_id = args.get("announcement_id")
        if announcement_id is not None:
            return self._show(str(announcement_id).strip(), args)
        return self._list(args)

    # -- list mode -----------------------------------------------------

    def _list(self, args: dict[str, Any]) -> ToolResult:
        cli_args = ["announcement"]
        if bool(args.get("force", False)):
            cli_args.append("--force")
        cli_args.append("list")
        if bool(args.get("all_term", False)):
            cli_args.append("--all-term")

        run = self._run(cli_args)
        if isinstance(run, ToolResult):
            return run

        announcements = _parse_list(run.stdout)

        course = args.get("course")
        if course:
            needle = str(course).casefold()
            announcements = [
                a for a in announcements if needle in a.course.casefold()
            ]

        limit = args.get("limit")
        if limit is not None:
            announcements = announcements[: int(limit)]

        total = _LIST_HEADER.search(run.stdout)
        return ToolResult(
            success=True,
            data={
                "announcements": [asdict(a) for a in announcements],
                "count": len(announcements),
                "total_reported": int(total.group(1)) if total else None,
            },
        )

    # -- detail mode ---------------------------------------------------

    def _show(self, announcement_id: str, args: dict[str, Any]) -> ToolResult:
        if not announcement_id:
            return ToolResult(
                success=False, error="announcement_id must be a non-empty string"
            )
        cli_args = ["announcement"]
        if bool(args.get("force", False)):
            cli_args.append("--force")
        cli_args.extend(["show", announcement_id])
        if bool(args.get("all_term", False)):
            cli_args.append("--all-term")

        run = self._run(cli_args)
        if isinstance(run, ToolResult):
            return run

        detail = _parse_detail(run.stdout, announcement_id)
        if detail is None:
            return ToolResult(
                success=False,
                error=(
                    f"could not parse `pku3b announcement show {announcement_id}` "
                    f"output (announcement not found, or the text format "
                    f"changed). Raw output:\n{run.stdout.strip()}"
                ),
            )
        return ToolResult(success=True, data={"announcement": asdict(detail)})

    # -- shared --------------------------------------------------------

    def _run(self, cli_args: list[str]) -> Any:
        """Run pku3b; return a :class:`Pku3bRun` or a failed :class:`ToolResult`."""
        try:
            run = run_pku3b(
                cli_args, executable=self.executable, timeout=self.timeout
            )
        except Pku3bNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))
        except Pku3bTimeoutError as exc:
            return ToolResult(success=False, error=str(exc))

        if not run.ok:
            err = run.stderr.strip() or run.stdout.strip() or "unknown error"
            return ToolResult(
                success=False, error=f"pku3b exited {run.returncode}: {err}"
            )
        return run


def _collapse(text: str) -> str:
    """Collapse all runs of whitespace (incl. newlines) into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_list(stdout: str) -> list[Announcement]:
    """Parse ``announcement list`` text into structured records.

    Each entry starts with a ``[ N]`` index marker. The trailing token of
    an entry is the announcement id; everything between the index and the
    id is ``<course> > <title>``. Titles may span multiple lines, so the
    text is split on index markers rather than on newlines.
    """
    starts = [m.start() for m in _ENTRY_START.finditer(stdout)]
    announcements: list[Announcement] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(stdout)
        block = stdout[start:end]

        head = _ENTRY_START.match(block)
        if head is None:  # pragma: no cover - guarded by finditer
            continue
        index = int(head.group(1))
        body = block[head.end() :]

        id_match = _TRAILING_ID.search(body)
        if id_match is None:
            continue
        announcement_id = id_match.group(1)
        course_title = body[: id_match.start()]

        if _SEPARATOR not in course_title:
            continue
        course, title = course_title.split(_SEPARATOR, 1)
        announcements.append(
            Announcement(
                index=index,
                course=_collapse(course),
                title=_collapse(title),
                id=announcement_id,
            )
        )
    return announcements


def _parse_detail(stdout: str, announcement_id: str) -> AnnouncementDetail | None:
    """Parse ``announcement show <id>`` text into a single record."""
    id_match = _DETAIL_ID.search(stdout)
    if id_match is None:
        return None
    parsed_id = id_match.group(1)

    # The "<course> > <title>" line sits just above the "ID:" line.
    head = stdout[: id_match.start()]
    course = ""
    title = ""
    for line in reversed(head.splitlines()):
        if _SEPARATOR in line:
            course_part, title_part = line.split(_SEPARATOR, 1)
            course = _collapse(course_part)
            title = _collapse(title_part)
            break

    posted = _POSTED_AT.search(stdout)
    body = stdout[id_match.end() :].strip()
    return AnnouncementDetail(
        id=parsed_id or announcement_id,
        course=course,
        title=title,
        posted_at=_collapse(posted.group(1)) if posted else None,
        body=body,
    )
