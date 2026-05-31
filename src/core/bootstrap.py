"""Bootstrap — single-call factory that assembles the Agent for the GUI.

Per `docs/integration_contract_zh.md`, the GUI calls only `build_agent()`
and never constructs concrete LLMProviders or Tools itself. That keeps
backend churn (new providers, new tools, swapped models) from rippling
into the GUI lane.
"""

from __future__ import annotations

from pathlib import Path

from ..llm import DeepSeekProvider, EchoLLMProvider, LLMProvider
from ..rag import (
    APIEmbedder,
    CalendarSource,
    Chunk,
    DeanSource,
    KnowledgeBase,
    SourceRegistry,
)
from ..tools import (
    ClockTool,
    KnowledgeSearchTool,
    LectureTool,
    MemoryTool,
    PKU3bAnnouncementsTool,
    PKU3bAssignmentsTool,
    PKU3bCourseTableTool,
    ReminderTool,
    WeatherTool,
)
from ..tools.base import ToolRegistry
from ..workflows import HelloWorkflow, MorningBriefingWorkflow
from ..workflows.base import WorkflowRegistry
from .agent import Agent
from .conversation import Conversation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEEPSEEK_KEY_PATH = _REPO_ROOT / "secrets" / "deepseek_key.txt"
_EMBEDDING_KEY_PATH = _REPO_ROOT / "secrets" / "embedding_key.txt"

_SYSTEM_PROMPT = (
    "You are PKU Captain, a desktop AI assistant for Peking University "
    "students. Reply in the user's language (default Chinese). When a "
    "registered tool can answer the user's question, prefer calling the "
    "tool over guessing. Be terse."
)


def build_agent(*, offline: bool = False, enable_knowledge: bool = False) -> Agent:
    """Assemble the Agent the GUI runs against.

    `offline=True` swaps in `EchoLLMProvider` and drops any tool that
    touches the network or a subprocess, so the GUI lane can develop
    without an API key or live PKU endpoints.

    `enable_knowledge` is opt-in (default off): RAG `knowledge_search`
    registers only when it is True *and* the agent is online. Leaving it
    off keeps startup free of any embedding-API calls.
    """
    llm = _build_llm(offline=offline)
    tools = _build_tools(offline=offline, enable_knowledge=enable_knowledge)
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


def _build_tools(*, offline: bool, enable_knowledge: bool = False) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClockTool())
    registry.register(MemoryTool())
    registry.register(ReminderTool())
    if not offline:
        registry.register(PKU3bAssignmentsTool())
        registry.register(PKU3bAnnouncementsTool())
        registry.register(PKU3bCourseTableTool())
        registry.register(WeatherTool())
        if enable_knowledge:
            registry.register(KnowledgeSearchTool(_build_knowledge_base()))
        registry.register(LectureTool())
    return registry


def _build_knowledge_base() -> KnowledgeBase:
    """Build an in-memory KnowledgeBase seeded from the registered Sources.

    Pulls chunks from every `Source` in `build_source_registry()` so the
    knowledge base retrieves over the same authoritative content the
    dashboard shows. Embedding goes through the DashScope API (no local
    model download), so indexing here calls the network — which is why
    the tool is opt-in (`enable_knowledge`) and online only.
    """
    knowledge_base = KnowledgeBase(embedder=_build_embedder())
    chunks: list[Chunk] = []
    for source in build_source_registry().all():
        chunks.extend(source.fetch())
    knowledge_base.index(chunks)
    return knowledge_base


def _build_embedder() -> APIEmbedder:
    """Construct the API embedder from the local key file."""
    if not _EMBEDDING_KEY_PATH.exists():
        raise FileNotFoundError(
            f"Embedding API key not found at {_EMBEDDING_KEY_PATH}. "
            "RAG knowledge search needs it; omit enable_knowledge to run without RAG."
        )
    api_key = _EMBEDDING_KEY_PATH.read_text(encoding="utf-8").strip()
    return APIEmbedder(api_key=api_key)


def _build_workflows(tools: ToolRegistry) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(HelloWorkflow(tools))
    registry.register(MorningBriefingWorkflow(tools))
    return registry


def build_source_registry() -> SourceRegistry:
    """Assemble the SourceRegistry the dashboard polls for RAG content.

    Per `docs/integration_contract_zh.md` §5, the dashboard (GUI lane)
    obtains its `SourceRegistry` through this factory and never
    constructs concrete `Source` subclasses itself.
    """
    registry = SourceRegistry()
    registry.register(DeanSource())
    registry.register(CalendarSource())
    return registry
