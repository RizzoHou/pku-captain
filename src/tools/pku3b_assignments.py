"""PKU3bAssignmentsTool — list course assignments from PKU 教学网 (Blackboard).

Drives the vendored :mod:`pypku3b` library **in-process** (no subprocess): each
invocation builds a fresh :class:`pypku3b.Client` via an injectable
``client_factory`` seam (tests inject a fake), authenticates from
``secrets/pku/{id,password}``, and returns each assignment's course, deadlines,
completion state, descriptions, attachments, and Blackboard links.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .pku3b import (
    DEFAULT_TIMEOUT,
    PKU_SECRETS_DIR,
    ClientFactory,
    Pku3bError,
    assignment_submit_url,
    default_client_factory,
    secret_values,
    stored_credentials,
)
from .redact import redact


class PKU3bAssignmentsTool(Tool):
    name: ClassVar[str] = "pku3b_assignments"
    description: ClassVar[str] = (
        "List course assignments from PKU 教学网 (Blackboard). Returns each "
        "assignment's course (short name + full title + course id), assignment "
        "title, raw + ISO-8601 deadlines, completion status, descriptions, and "
        "attachment names + Blackboard URIs. Use this to answer questions like "
        "“今天有什么作业？” / “这周要交什么？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "include_completed": {
                "type": "boolean",
                "description": (
                    "If true, also include assignments that have already been "
                    "submitted. Default: false."
                ),
                "default": False,
            }
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        secrets_dir: Path | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self.secrets_dir = secrets_dir or PKU_SECRETS_DIR
        self._client_factory = client_factory or default_client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        include_completed = bool(args.get("include_completed", False))
        try:
            client = self._client_factory(
                secrets_dir=self.secrets_dir,
                timeout=self.timeout,
                credentials=stored_credentials(self.secrets_dir),
            )
            assignments = client.list_assignments(include_completed=include_completed)
        except Pku3bError as exc:
            message = getattr(exc, "message", str(exc))
            return ToolResult(
                success=False,
                error=redact(message, secret_values(self.secrets_dir)),
            )

        return ToolResult(
            success=True,
            data={"assignments": [_to_record(a) for a in assignments]},
        )


def _to_record(a: Any) -> dict[str, Any]:
    """Map a ``pypku3b.Assignment`` to the tool's stable output shape."""
    submit_url = assignment_submit_url(a.course_id, a.content_id)
    return {
        "id": a.id,
        "course_name": a.course_name,
        "course_title": a.course_title,
        "course_id": a.course_id,
        "title": a.title,
        "deadline_raw": a.deadline_raw,
        "deadline_iso": a.deadline_iso,
        "completed": a.completed,
        "last_attempt": a.last_attempt,
        "descriptions": list(a.descriptions),
        "attachments": [{"name": att.name, "uri": att.uri} for att in a.attachments],
        "url": a.course_url,
        "submit_url": submit_url,
        "blackboard_content_id": a.content_id or None,
    }
