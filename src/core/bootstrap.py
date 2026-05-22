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
    CalendarSource,
    Chunk,
    DeanSource,
    KnowledgeBase,
    SourceRegistry,
    StaticSource,
)
from ..tools import ClockTool, KnowledgeSearchTool, PKU3bAssignmentsTool, WeatherTool
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


# Built-in seed corpus for the knowledge base. The captain swaps in real
# sources (DeanSource, CalendarSource) during integration; until then this
# gives KnowledgeSearchTool something concrete to retrieve over.
_SAMPLE_CHUNKS: tuple[Chunk, ...] = (
    Chunk(
        source_name="sample",
        identifier="calendar-2026-spring",
        text="北京大学2026年春季学期：2月23日开学，6月22日至7月3日为考试周，7月4日起放暑假。",
        metadata={"topic": "academic_calendar"},
    ),
    Chunk(
        source_name="sample",
        identifier="library-hours",
        text="北京大学图书馆开放时间：周一至周日7:00至22:30，考试周延长至23:30闭馆。",
        metadata={"topic": "library"},
    ),
    Chunk(
        source_name="sample",
        identifier="course-drop",
        text="退课办理：开学后两周内可通过教务系统自由退课，逾期需经院系审批。",
        metadata={"topic": "registration"},
    ),
    Chunk(
        source_name="sample",
        identifier="dining-hall",
        text="学校食堂用餐：燕南、农园、家园等食堂支持校园卡和手机扫码支付，早餐7:00开始供应。",
        metadata={"topic": "dining"},
    ),
)


def _build_tools(*, offline: bool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClockTool())
    if not offline:
        registry.register(PKU3bAssignmentsTool())
        registry.register(WeatherTool())
        registry.register(KnowledgeSearchTool(_build_knowledge_base()))
    return registry


def _build_knowledge_base() -> KnowledgeBase:
    """Build an in-memory KnowledgeBase seeded with the sample corpus.

    Indexing here loads the BGE embedding model, which is why the tool
    is registered online only — offline GUI development never reaches
    this path.
    """
    knowledge_base = KnowledgeBase()
    knowledge_base.index(StaticSource(_SAMPLE_CHUNKS).fetch())
    return knowledge_base


def _build_workflows(tools: ToolRegistry) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(HelloWorkflow(tools))
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
