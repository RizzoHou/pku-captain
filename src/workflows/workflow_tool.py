"""WorkflowTool — adapter exposing a Workflow as an agent-callable Tool.

Workflows compose tools into multi-step tasks but, unlike Tools, were
historically reachable only through the GUI workflow button — `Agent.turn()`
serializes `self.tools.to_openai_schema()` to the LLM, so the model never
saw a workflow and could not start one on its own.

This adapter bridges the two parallel hierarchies: it wraps any `Workflow`
as a `Tool`, forwarding the workflow's name / description / parameters_schema
into the tool schema and mapping the returned `WorkflowResult` back to a
`ToolResult`. Registering one adapter per workflow in the agent's
`ToolRegistry` (see `core.bootstrap`) makes every workflow callable by the
model through the normal tool-call loop, while the GUI button path
(`WorkflowWorker` over `agent.workflows`) is left untouched.
"""

from __future__ import annotations

from typing import Any

from ..tools.base import Tool, ToolResult
from .base import Workflow


class WorkflowTool(Tool):
    """Expose a single `Workflow` to the agent as a callable `Tool`."""

    # The base declares name/description/parameters_schema as ClassVars, but
    # each adapter mirrors a different wrapped workflow, so they must be set
    # per instance. mypy forbids assigning to a ClassVar via an instance;
    # the bridge is intentional, so the conflict is suppressed per line.
    def __init__(self, workflow: Workflow) -> None:
        self._workflow = workflow
        self.name = workflow.name  # type: ignore[misc]
        self.description = workflow.description  # type: ignore[misc]
        self.parameters_schema = workflow.parameters_schema  # type: ignore[misc]

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        result = self._workflow.run(args or None)
        if result.success:
            # `summary` is the human-readable rendering the model relays;
            # the structured `details` are dropped to keep the tool-result
            # payload (stringified back to the LLM) compact.
            return ToolResult(success=True, data=result.summary)
        return ToolResult(success=False, error=result.error or result.summary)
