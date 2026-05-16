"""PKU3bAssignmentsTool — fetch course assignments via the ``pku3b`` CLI.

Calls ``pku3b assignment list --format json`` (from our fork at
``github.com/RizzoHou/pku3b`` branch ``feat/assignment-list-json-output``)
and consumes the structured JSON directly — no text parsing.

By default only outstanding assignments are returned; set
``include_completed=True`` to pass ``--all`` through to ``pku3b``.
"""

from __future__ import annotations

import json
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
    attachments: list[dict[str, str]] = field(default_factory=list)


class PKU3bAssignmentsTool(Tool):
    name: ClassVar[str] = "pku3b_assignments"
    description: ClassVar[str] = (
        "List course assignments from PKU 教学网 (Blackboard) via the local "
        "`pku3b` CLI. Returns each assignment's course (short name + full "
        "title + course id), assignment title, raw + ISO-8601 deadlines, "
        "completion status, descriptions, and attachment names + Blackboard "
        "URIs. Use this to answer questions like “今天有什么作业？” / "
        "“这周要交什么？”."
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
        cli_args = ["assignment", "list", "--format", "json"]
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

        try:
            records = json.loads(run.stdout)
        except json.JSONDecodeError as exc:
            return ToolResult(
                success=False,
                error=(
                    f"failed to parse pku3b JSON output: {exc}. "
                    "Confirm the installed binary supports `--format json` "
                    "(install our fork: "
                    "`cargo install --git https://github.com/RizzoHou/pku3b "
                    "--branch feat/assignment-list-json-output`)."
                ),
            )

        assignments = [_record_to_assignment(r) for r in records]
        return ToolResult(
            success=True,
            data={"assignments": [asdict(a) for a in assignments]},
        )


def _record_to_assignment(record: dict[str, Any]) -> Assignment:
    return Assignment(
        id=record["id"],
        course_name=record["course_name"],
        course_title=record["course_title"],
        course_id=record["course_id"],
        title=record["title"],
        deadline_raw=record.get("deadline_raw"),
        deadline_iso=record.get("deadline_iso"),
        completed=bool(record.get("completed", False)),
        last_attempt=record.get("last_attempt"),
        descriptions=list(record.get("descriptions") or []),
        attachments=[dict(a) for a in (record.get("attachments") or [])],
    )
