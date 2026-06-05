"""Bootstrap — single-call factory that assembles the Agent for the GUI.

Per `docs/integration_contract_zh.md`, the GUI calls only `build_agent()`
and never constructs concrete LLMProviders or Tools itself. That keeps
backend churn (new providers, new tools, swapped models) from rippling
into the GUI lane.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..llm import ChatMessage, DeepSeekProvider, EchoLLMProvider, LLMProvider
from ..rag import (
    APIEmbedder,
    CalendarSource,
    Chunk,
    DeanSource,
    KnowledgeBase,
    SourceRegistry,
)
from ..tools import (
    CalendarReminderTool,
    ClockTool,
    DeanResourcesTool,
    DeanUpdatesTool,
    KnowledgeSearchTool,
    LectureTool,
    MemoryTool,
    PKU3bAnnouncementsTool,
    PKU3bAssignmentsTool,
    PKU3bCourseTableTool,
    PLibMaterialsTool,
    ReminderTool,
    TreeholeTool,
    TreeholeUpdatesTool,
)
from ..tools.base import ToolRegistry
from ..tools.pku3b import Pku3bNotFoundError, Pku3bTimeoutError, run_pku3b
from ..workflows import HelloWorkflow, MorningBriefingWorkflow
from ..workflows.base import WorkflowRegistry
from .agent import Agent
from .conversation import Conversation
from .dashboard_cache import DashboardCache
from .memory import MemoryStore
from .session_store import (
    SessionStore,
    deserialize_messages,
    drop_incomplete_tool_calls,
)
from .session_titler import SessionTitler

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECRETS_DIR = _REPO_ROOT / "secrets"
# Canonical layout: secrets/api_keys/<provider>_key.txt. The flat
# secrets/<provider>_key.txt paths are kept as a fallback for older checkouts.
_DEEPSEEK_KEY_PATHS = (
    _SECRETS_DIR / "api_keys" / "deepseek_key.txt",
    _SECRETS_DIR / "deepseek_key.txt",
)
_EMBEDDING_KEY_PATHS = (
    _SECRETS_DIR / "api_keys" / "embedding_key.txt",
    _SECRETS_DIR / "embedding_key.txt",
)

_SYSTEM_PROMPT = (
    "You are PKU Captain, a desktop AI assistant for Peking University "
    "students. Reply in the user's language (default Chinese). When a "
    "registered tool can answer the user's question, prefer calling the "
    "tool over guessing. Be terse.\n"
    "Learn about the user as you talk. Whenever the user states a durable "
    "fact about themselves — their name, school or major, where they live, "
    "preferred reply language, a recurring schedule, or a stable preference "
    "relevant to helping them — call the `memory` tool with action "
    "`remember` and the fact as plain `text` (no key needed). Use action "
    "`set` with a stable key only when updating a value that should replace "
    "a previously stored one. Do not store one-off or transient details. "
    "Any facts already known about the user are listed under \"Known facts "
    "about the user\" below; use them to personalize replies and never ask "
    "again for something already stored."
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
    # One shared store: the MemoryTool writes to it and the Agent reads it
    # back when folding memory into each turn's context. A second instance on
    # the same path would never see mid-session writes (it loads once at
    # construction), so the feature would silently no-op — keep it shared.
    memory = MemoryStore()
    if not offline:
        _sync_pku3b_identity_memory(memory)
    tools = _build_tools(
        offline=offline, enable_knowledge=enable_knowledge, memory=memory
    )
    workflows = _build_workflows(tools)

    conversation = Conversation()
    conversation.add_system(_SYSTEM_PROMPT)

    return Agent(
        llm=llm,
        tools=tools,
        workflows=workflows,
        conversation=conversation,
        memory=memory,
    )


def build_session_store() -> SessionStore:
    """Construct the session store the GUI persists conversations through."""
    return SessionStore()


def build_dashboard_cache() -> DashboardCache:
    """Construct the per-card cache the dashboard saves/restores its data through."""
    return DashboardCache()


def build_session_titler(*, offline: bool) -> SessionTitler:
    """Construct the auto-namer for chat sessions.

    Online → a lightweight `deepseek-v4-flash` provider in non-think mode
    (cheap, fast, no reasoning). Offline, or when the DeepSeek key is
    missing, → a provider-less titler that falls back to a heuristic title
    (so it never raises and never routes through `EchoLLMProvider`).
    """
    if offline:
        return SessionTitler(None)
    key_path = _find_key_path(_DEEPSEEK_KEY_PATHS)
    if key_path is None:
        return SessionTitler(None)
    api_key = key_path.read_text(encoding="utf-8").strip()
    return SessionTitler(
        DeepSeekProvider(api_key=api_key, model="deepseek-v4-flash", thinking=False)
    )


def reset_conversation(agent: Agent) -> None:
    """Reset the agent's conversation to a fresh, system-seeded state.

    Centralises the write so the GUI never calls `Conversation.add_*`
    directly (integration contract §1).
    """
    agent.conversation.load_messages([])
    agent.conversation.add_system(_SYSTEM_PROMPT)


def restore_conversation(agent: Agent, raw_messages: list[dict[str, Any]]) -> None:
    """Load a saved session (stored JSON message dicts) into the conversation.

    Deserialization stays in `core` so the GUI never touches the wire
    format. Any persisted `system` message is dropped and the *current*
    `_SYSTEM_PROMPT` is re-seeded, so reopening an old session runs under
    today's instructions rather than a stale saved prompt. After this, the
    GUI renders history from `agent.conversation.snapshot()`.
    """
    restored = drop_incomplete_tool_calls(deserialize_messages(raw_messages))
    body = [m for m in restored if m.role != "system"]
    agent.conversation.load_messages(
        [ChatMessage(role="system", content=_SYSTEM_PROMPT), *body]
    )


def _build_llm(*, offline: bool) -> LLMProvider:
    if offline:
        return EchoLLMProvider()
    key_path = _find_key_path(_DEEPSEEK_KEY_PATHS)
    if key_path is None:
        expected = " or ".join(str(path) for path in _DEEPSEEK_KEY_PATHS)
        raise FileNotFoundError(
            f"DeepSeek API key not found at {expected}. "
            "Either provide the key file or call build_agent(offline=True)."
        )
    api_key = key_path.read_text(encoding="utf-8").strip()
    return DeepSeekProvider(api_key=api_key)


def _build_tools(
    *, offline: bool, enable_knowledge: bool = False, memory: MemoryStore | None = None
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClockTool())
    registry.register(MemoryTool(store=memory))
    registry.register(ReminderTool())
    if not offline:
        registry.register(PKU3bAssignmentsTool())
        registry.register(PKU3bAnnouncementsTool())
        registry.register(PKU3bCourseTableTool())
        registry.register(PLibMaterialsTool())
        registry.register(TreeholeTool())
        registry.register(TreeholeUpdatesTool())
        registry.register(CalendarReminderTool())
        registry.register(DeanResourcesTool())
        registry.register(DeanUpdatesTool())
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
    key_path = _find_embedding_key_path()
    if key_path is None:
        expected = " or ".join(str(path) for path in _EMBEDDING_KEY_PATHS)
        raise FileNotFoundError(
            f"Embedding API key not found at {expected}. "
            "RAG knowledge search needs it; omit enable_knowledge to run without RAG."
        )
    api_key = key_path.read_text(encoding="utf-8").strip()
    return APIEmbedder(api_key=api_key)


_IDENTITY_MEMORY_FIELDS = {
    "name": "identity.name",
    "student_id": "identity.student_id",
    "department": "identity.department",
    "speciality": "identity.speciality",
    "direction": "identity.direction",
    "student_type": "identity.student_type",
    "user_identity": "identity.user_identity",
}


def _sync_pku3b_identity_memory(memory: MemoryStore) -> None:
    """Best-effort startup sync of pku3b identity into long-term memory.

    Uses ``identity --format json`` rather than ``--raw`` so the CLI returns the
    public student identity summary only, not the full portal record. Startup
    must stay robust: missing pku3b, expired login, OTP/network errors, or
    schema changes should leave memory unchanged rather than preventing the GUI
    from opening.

    Sync-once: ``MemoryStore`` persists to disk, so once any identity field is
    stored we skip the blocking ``pku3b identity`` subprocess on later launches.
    This call runs on the GUI main thread inside ``build_agent``; re-authing the
    portal every launch would freeze startup and risk tripping OTP/rate limits.
    """
    if any(memory.get(key) is not None for key in _IDENTITY_MEMORY_FIELDS.values()):
        return
    try:
        run = run_pku3b(["identity", "--format", "json"])
    except (Pku3bNotFoundError, Pku3bTimeoutError, OSError):
        return
    if not run.ok:
        return
    try:
        payload = json.loads(run.stdout)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    for field, key in _IDENTITY_MEMORY_FIELDS.items():
        value = payload.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            memory.set(key, text)


def _find_key_path(paths: tuple[Path, ...]) -> Path | None:
    """Return the first existing path in a fallback tuple, else None."""
    for path in paths:
        if path.exists():
            return path
    return None


def _find_embedding_key_path() -> Path | None:
    return _find_key_path(_EMBEDDING_KEY_PATHS)


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
