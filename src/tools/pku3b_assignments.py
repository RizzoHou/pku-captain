"""PKU3bAssignmentsTool — fetch course assignments via the ``pku3b`` CLI.

Wraps ``pku3b assignment list`` (alias ``pku3b a ls``). The CLI prints a
human-readable, ANSI-coloured listing grouped by section (未完成 / 已完成).
This tool runs the subprocess, strips colour, parses the listing into
structured records, and returns both the structured form and the cleaned
raw text — the latter is useful when the parser misses a corner case
and the LLM still has to ground its reply in something concrete.

By default only outstanding assignments are returned; set
``include_completed=True`` to pass ``--all`` through to ``pku3b``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_EXECUTABLE,
    DEFAULT_TIMEOUT,
    Pku3bNotFoundError,
    Pku3bTimeoutError,
    run_pku3b,
)

_SECTION_RE = re.compile(r"^>\s*(?P<title>.+?)\s*<\s*$")
_ASSIGNMENT_RE = re.compile(
    r"^(?P<course>.+?)\s+>\s+(?P<title>.+?)\s+\((?P<deadline>[^()]+)\)\s+"
    r"(?P<id>[0-9a-fA-F]{8,})\s*$"
)
_ATTACHMENT_RE = re.compile(r"^\[附件\]\s*(?P<name>.+?)\s*$")


@dataclass
class Assignment:
    course: str
    title: str
    deadline: str
    id: str
    section: str | None = None
    description: str = ""
    attachments: list[str] = field(default_factory=list)


class PKU3bAssignmentsTool(Tool):
    name: ClassVar[str] = "pku3b_assignments"
    description: ClassVar[str] = (
        "List course assignments from PKU 教学网 (Blackboard) via the local "
        "`pku3b` CLI. Returns each assignment's course, title, deadline, id, "
        "and any attachment filenames. Use this to answer questions like "
        "“今天有什么作业？” / “这周要交什么？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "include_completed": {
                "type": "boolean",
                "description": (
                    "If true, also include assignments that have already been "
                    "submitted (passes --all to pku3b). Default: false."
                ),
                "default": False,
            }
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
        include_completed = bool(args.get("include_completed", False))
        cli_args = ["assignment", "list"]
        if include_completed:
            cli_args.append("--all")

        try:
            run = run_pku3b(cli_args, executable=self.executable, timeout=self.timeout)
        except Pku3bNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))
        except Pku3bTimeoutError as exc:
            return ToolResult(success=False, error=str(exc))

        if not run.ok:
            err = run.stderr.strip() or run.stdout.strip() or "unknown error"
            return ToolResult(
                success=False,
                error=f"pku3b exited {run.returncode}: {err}",
            )

        assignments = parse_assignment_list(run.stdout)
        return ToolResult(
            success=True,
            data={
                "assignments": [asdict(a) for a in assignments],
                "raw": run.stdout,
            },
        )


def parse_assignment_list(text: str) -> list[Assignment]:
    """Parse the ANSI-stripped output of ``pku3b assignment list``.

    Best-effort: the CLI's output format is not contractually stable, so
    on a parse miss we keep going rather than raise. Description lines
    between an assignment header and the next assignment (or attachment
    block) are collected verbatim.
    """
    assignments: list[Assignment] = []
    current_section: str | None = None
    current: Assignment | None = None
    pending_desc: list[str] = []

    def flush_desc() -> None:
        if current is not None and pending_desc:
            current.description = "\n".join(pending_desc).strip()
        pending_desc.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        section_match = _SECTION_RE.match(line)
        if section_match:
            flush_desc()
            current = None
            current_section = section_match.group("title").strip()
            continue

        assignment_match = _ASSIGNMENT_RE.match(line)
        if assignment_match:
            flush_desc()
            current = Assignment(
                course=assignment_match.group("course").strip(),
                title=assignment_match.group("title").strip(),
                deadline=assignment_match.group("deadline").strip(),
                id=assignment_match.group("id").strip(),
                section=current_section,
            )
            assignments.append(current)
            continue

        attachment_match = _ATTACHMENT_RE.match(line)
        if attachment_match and current is not None:
            flush_desc()
            current.attachments.append(attachment_match.group("name").strip())
            continue

        if current is not None:
            pending_desc.append(line)

    flush_desc()
    return assignments
