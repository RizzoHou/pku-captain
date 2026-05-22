"""Bootstrap — single-call factory that assembles the Agent for the GUI.

Per `docs/integration_contract_zh.md`, the GUI calls only `build_agent()`
and never constructs concrete LLMProviders or Tools itself. That keeps
backend churn (new providers, new tools, swapped models) from rippling
into the GUI lane.
"""

from __future__ import annotations

from pathlib import Path

from ..llm import DeepSeekProvider, EchoLLMProvider, LLMProvider
from ..tools import ClockTool, LectureTool, PKU3bAssignmentsTool, WeatherTool
from ..tools.base import ToolRegistry
from ..workflows import HelloWorkflow
from ..workflows.base import WorkflowRegistry
from .agent import Agent
from .conversation import Conversation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEEPSEEK_KEY_PATH = _REPO_ROOT / "secrets" / "deepseek_key.txt"

_SYSTEM_PROMPT = (
    "You are PKU Captain, a desktop AI assistant for Peking University "
    "students. Reply in the user's language (default Chinese). When a "
    "registered tool can answer the user's question, prefer calling the "
    "tool over guessing. Be terse."
)


def build_agent(*, offline: bool = False) -> Agent:
    """Assemble the Agent the GUI runs against.

    `offline=True` swaps in `EchoLLMProvider` and drops any tool that
    touches the network or a subprocess, so the GUI lane can develop
    without an API key or live PKU endpoints.
    """
    llm = _build_llm(offline=offline)
    tools = _build_tools(offline=offline)
    workflows = _build_workflows(tools)

    conversation = Conversation()
    conversation.add_system(_SYSTEM_PROMPT)

    return Agent(
        llm=llm,
        tools=tools,
        workflows=workflows,
        conversation=conversation,
    )


def _build_llm(*, offline: bool) -> LLMProvider:
    if offline:
        return EchoLLMProvider()
    if not _DEEPSEEK_KEY_PATH.exists():
        raise FileNotFoundError(
            f"DeepSeek API key not found at {_DEEPSEEK_KEY_PATH}. "
            "Either provide the key file or call build_agent(offline=True)."
        )
    api_key = _DEEPSEEK_KEY_PATH.read_text(encoding="utf-8").strip()
    return DeepSeekProvider(api_key=api_key)


def _build_tools(*, offline: bool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClockTool())
    if not offline:
        registry.register(PKU3bAssignmentsTool())
        registry.register(WeatherTool())
        registry.register(LectureTool())
    return registry


def _build_workflows(tools: ToolRegistry) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(HelloWorkflow(tools))
    return registry
