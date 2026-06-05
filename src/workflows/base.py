"""Workflow abstract base class and registry.

A Workflow composes multiple tool calls into a multi-step task (e.g.
MorningBriefing, WeeklyReview). Subclasses receive a ToolRegistry at
construction and orchestrate calls in `run`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..tools.base import ToolRegistry


@dataclass(frozen=True)
class WorkflowResult:
    success: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Workflow(ABC):
    """Abstract multi-step task that composes tool calls."""

    name: ClassVar[str]
    description: ClassVar[str]
    # JSON schema for the args dict `run` accepts; defaults to the
    # no-argument shape. Param'd workflows override it, and the
    # WorkflowTool adapter surfaces it into the LLM tool schema so the
    # model knows how (if at all) to parameterize the workflow.
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    @abstractmethod
    def run(self, args: dict[str, Any] | None = None) -> WorkflowResult:
        """Execute the workflow end-to-end."""


@dataclass
class WorkflowRegistry:
    _workflows: dict[str, Workflow] = field(default_factory=dict)

    def register(self, workflow: Workflow) -> None:
        if workflow.name in self._workflows:
            raise ValueError(f"workflow already registered: {workflow.name}")
        self._workflows[workflow.name] = workflow

    def get(self, name: str) -> Workflow:
        return self._workflows[name]

    def all(self) -> list[Workflow]:
        return list(self._workflows.values())
