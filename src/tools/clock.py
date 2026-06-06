"""ClockTool — reference Tool subclass.

A no-network, no-argument tool that returns the current local time. Useful
as a smoke-test target for the agent loop and as a minimal example of the
Tool / ToolRegistry pattern. Real tools (PKU3bAssignmentsTool,
PKU3bAnnouncementsTool, ...) follow the same shape with real backends.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from .base import Tool, ToolResult

_TZ = ZoneInfo("Asia/Shanghai")


class ClockTool(Tool):
    name: ClassVar[str] = "clock"
    description: ClassVar[str] = "Return the current time in Asia/Shanghai as an ISO-8601 string."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, data=datetime.now(_TZ).isoformat(timespec="seconds"))
