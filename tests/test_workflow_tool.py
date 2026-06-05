"""Unit tests for `WorkflowTool` — the adapter that makes a Workflow agent-callable.

These cover the offline plumbing: the adapter mirrors a workflow's schema
fields, maps WorkflowResult -> ToolResult correctly, and `build_agent`
registers one adapter per workflow into the ToolRegistry so the workflow
reaches the LLM tool schema while the GUI button path stays intact. The
live proof that DeepSeek actually *chooses* a workflow tool lives in
`scripts/smoke_workflow.py` (needs the API key, not run in CI).
"""

from __future__ import annotations

from typing import Any

from src.core import build_agent
from src.tools.base import ToolRegistry, ToolResult
from src.tools.clock import ClockTool
from src.workflows import HelloWorkflow, Workflow, WorkflowResult, WorkflowTool


class _FailingWorkflow(Workflow):
    name = "boom"
    description = "Always fails, with an explicit error string."

    def run(self, args: dict[str, Any] | None = None) -> WorkflowResult:
        return WorkflowResult(success=False, summary="boom summary", error="kaboom")


class _QuietFailWorkflow(Workflow):
    name = "quiet_fail"
    description = "Fails without an error string."

    def run(self, args: dict[str, Any] | None = None) -> WorkflowResult:
        return WorkflowResult(success=False, summary="only summary", error=None)


def _hello() -> HelloWorkflow:
    tools = ToolRegistry()
    tools.register(ClockTool())
    return HelloWorkflow(tools)


def test_adapter_mirrors_workflow_schema_fields() -> None:
    workflow = _hello()
    tool = WorkflowTool(workflow)
    assert tool.name == workflow.name == "hello"
    assert tool.description == workflow.description
    assert tool.parameters_schema == workflow.parameters_schema
    # Default schema is the no-argument shape.
    assert tool.parameters_schema["type"] == "object"
    assert tool.parameters_schema["properties"] == {}


def test_invoke_maps_success_to_tool_result() -> None:
    tool = WorkflowTool(_hello())
    result = tool.invoke({})
    assert isinstance(result, ToolResult)
    assert result.success
    # `data` carries the workflow's human-readable summary, not its details.
    assert isinstance(result.data, str)
    assert result.data.startswith("Hello!")


def test_invoke_maps_failure_to_tool_result_error() -> None:
    tool = WorkflowTool(_FailingWorkflow(ToolRegistry()))
    result = tool.invoke({})
    assert not result.success
    assert result.error == "kaboom"


def test_invoke_failure_falls_back_to_summary_when_no_error() -> None:
    tool = WorkflowTool(_QuietFailWorkflow(ToolRegistry()))
    result = tool.invoke({})
    assert not result.success
    assert result.error == "only summary"


def test_build_agent_registers_workflow_tools() -> None:
    # The actual claim: workflows reach the LLM tool schema, not only the GUI
    # button. Offline so no API key is needed.
    agent = build_agent(offline=True)

    # Registered as callable tools...
    assert "morning_briefing" in agent.tools
    assert "hello" in agent.tools

    # ...and present in the schema the LLM receives.
    schema_names = {t["function"]["name"] for t in agent.tools.to_openai_schema()}
    assert {"morning_briefing", "hello"} <= schema_names

    # The GUI button path is untouched: the workflows still live in their
    # own registry too.
    assert {w.name for w in agent.workflows.all()} == {"morning_briefing", "hello"}


def test_registered_workflow_tool_runs_end_to_end() -> None:
    # Invoking the wired adapter offline exercises the whole path: tool
    # registry -> WorkflowTool -> Workflow.run -> ToolResult. `hello` only
    # needs `clock`, which is registered offline, so it succeeds.
    agent = build_agent(offline=True)
    result = agent.tools.get("hello").invoke({})
    assert result.success
    assert "Hello!" in str(result.data)
