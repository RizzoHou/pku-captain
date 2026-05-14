"""HelloWorkflow — reference Workflow subclass.

Demonstrates the simplest possible composition: invoke a single Tool
(`clock` by default) and wrap the result in a WorkflowResult. Real
Week-2 workflows (MorningBriefingWorkflow, WeeklyReviewWorkflow) chain
multiple tools and apply summarization on top.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Workflow, WorkflowResult


class HelloWorkflow(Workflow):
    name: ClassVar[str] = "hello"
    description: ClassVar[str] = "Greet the user with the current time via the clock tool."

    def run(self, args: dict[str, Any] | None = None) -> WorkflowResult:
        result = self.tools.get("clock").invoke({})
        if not result.success:
            return WorkflowResult(
                success=False,
                summary="clock tool failed",
                error=result.error,
            )
        return WorkflowResult(
            success=True,
            summary=f"Hello! The time is {result.data}.",
            details={"clock": result.data},
        )
