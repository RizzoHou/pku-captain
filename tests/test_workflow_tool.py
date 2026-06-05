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
from src.workflows import (
    HelloWorkflow,
    MorningBriefingWorkflow,
    Workflow,
    WorkflowResult,
    WorkflowTool,
)


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


def test_demo_workflow_opts_out_of_agent_tools() -> None:
    # The `agent_callable` flag is the gate: real workflows expose; reference
    # stubs do not. Default on the base is True.
    assert MorningBriefingWorkflow(ToolRegistry()).agent_callable is True
    assert HelloWorkflow(ToolRegistry()).agent_callable is False
    assert Workflow.agent_callable is True


def test_build_agent_registers_agent_callable_workflows_only() -> None:
    # The actual claim: agent-callable workflows reach the LLM tool schema,
    # not only the GUI button; the `hello` demo stub is filtered out. Offline
    # so no API key is needed.
    agent = build_agent(offline=True)

    # The real workflow is a callable tool, in the schema the LLM receives.
    assert "morning_briefing" in agent.tools
    schema_names = {t["function"]["name"] for t in agent.tools.to_openai_schema()}
    assert "morning_briefing" in schema_names

    # The demo stub is NOT exposed to the agent...
    assert "hello" not in agent.tools
    assert "hello" not in schema_names

    # ...yet both still live in the WorkflowRegistry, so the GUI button path
    # and the offline reference stub are untouched.
    assert {w.name for w in agent.workflows.all()} == {"morning_briefing", "hello"}


def test_registered_workflow_tool_runs_end_to_end() -> None:
    # Invoking the wired adapter offline exercises the whole path: tool
    # registry -> WorkflowTool -> Workflow.run -> ToolResult. Offline has no
    # reachable data sources, so morning_briefing degrades to a failed
    # ToolResult rather than raising — proof the full path ran.
    agent = build_agent(offline=True)
    result = agent.tools.get("morning_briefing").invoke({})
    assert isinstance(result, ToolResult)
    assert not result.success
