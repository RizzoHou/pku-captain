"""Bootstrap — single-call factory that assembles the Agent for the GUI.

Per `docs/integration_contract_zh.md`, the GUI calls only `build_agent()`
and never constructs concrete LLMProviders or Tools itself. That keeps
backend churn (new providers, new tools, swapped models) from rippling
into the GUI lane.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..llm import (
    ChatMessage,
    DeepSeekProvider,
    EchoLLMProvider,
    KimiProvider,
    LLMProvider,
)
from ..rag import CalendarSource, DeanSource, SourceRegistry
from ..tools import (
    CalendarReminderTool,
    ClockTool,
    DeanResourcesTool,
    DeanUpdatesTool,
    DocBaseReader,
    DocBaseReadTool,
    DocBaseSearchTool,
    MemoryTool,
    PKU3bAnnouncementsTool,
    PKU3bAssignmentsTool,
    PKU3bCourseTableTool,
    PLibMaterialsTool,
    TreeholeTool,
    TreeholeUpdatesTool,
)
from ..tools.base import ToolRegistry
from ..tools.pku3b import (
    PKU_SECRETS_DIR,
    Pku3bError,
    default_client_factory,
    stored_credentials,
)
from ..workflows import HelloWorkflow, WorkflowTool
from ..workflows.base import WorkflowRegistry
from .agent import Agent
from .conversation import Conversation
from .credentials import CredentialStore, ModelConfig
from .dashboard_cache import DashboardCache
from .memory import MemoryStore
from .network import apply_proxy
from .session_store import (
    SessionStore,
    deserialize_messages,
    drop_incomplete_tool_calls,
)
from .session_titler import SessionTitler

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECRETS_DIR = _REPO_ROOT / "secrets"

# Chat brains are now two configurable *roles* rather than two hard-coded
# brands: `text` (default DeepSeek, thinking wire format) and `visual` (default
# Kimi, vision-capable — reads doc_read's page images). Each role's endpoint /
# model / key live in the CredentialStore (`secrets/models.json`, with the
# legacy `secrets/api_keys/<brand>_key.txt` honoured as an api_key fallback), so
# a user can point either role at any OpenAI-compatible endpoint; DeepSeek/Kimi
# are only the defaults. `text` is the default brain. This dict holds only the
# implementation identity — the label + which provider class + whether it is
# vision-capable; the credentials live in `CredentialStore.model(role)`.
DEFAULT_CHAT_MODEL = "text"
_CHAT_MODELS: dict[str, dict[str, Any]] = {
    "text": {"label": "文本模型", "provider": "deepseek", "vision": False},
    "visual": {"label": "视觉模型", "provider": "kimi", "vision": True},
}


def _store() -> CredentialStore:
    """The credential store the model builders read from.

    A tiny indirection so tests can point the whole model layer at a tmp
    ``secrets/`` by monkeypatching ``bootstrap._store`` (mirrors the old
    ``_find_key_path`` monkeypatch pattern).
    """
    return CredentialStore()


def _build_role_provider(cfg: ModelConfig, provider: str) -> LLMProvider:
    """Instantiate the provider class for a role from its resolved config."""
    if provider == "kimi":
        return KimiProvider(
            api_key=cfg.api_key,
            model=cfg.model,
            base_url=cfg.base_url,
            context_window=cfg.context_window,
        )
    return DeepSeekProvider(
        api_key=cfg.api_key,
        model=cfg.model,
        base_url=cfg.base_url,
        context_window=cfg.context_window,
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
    "again for something already stored.\n"
    "For questions about PKU 培养方案 (curriculum / 学分 requirements / 课程设置), "
    "选课 (course selection handbook), or 辅修/双学位, first call `doc_search` to "
    "find the right document by 学院/专业, then call `doc_read` with that "
    "document's `path` (and a focused `question`) to read its actual tables — "
    "do not guess credit numbers or course lists from memory."
)


def build_agent(*, offline: bool = False) -> Agent:
    """Assemble the Agent the GUI runs against.

    `offline=True` swaps in `EchoLLMProvider` and drops any tool that
    touches the network or a subprocess, so the GUI lane can develop
    without an API key or live PKU endpoints.

    The doc base replaces the old RAG knowledge base: `doc_search` registers
    in every mode (it reads the committed manifest, no index to build). The
    `doc_read` tool feeds page images to a vision-capable chat brain, so it is
    registered only while the active brain is Kimi (the default brain is
    DeepSeek, so it starts unregistered; `apply_chat_model` toggles it).
    """
    # Proxy first: everything below (identity sync, tools, providers) must
    # already honour the user's 网络代理 setting on its first request.
    apply_proxy(_store().proxy())
    llm = _build_llm(offline=offline)
    # One shared store: the MemoryTool writes to it and the Agent reads it
    # back when folding memory into each turn's context. A second instance on
    # the same path would never see mid-session writes (it loads once at
    # construction), so the feature would silently no-op — keep it shared.
    memory = MemoryStore()
    if not offline:
        _sync_pku3b_identity_memory(memory)
    tools = _build_tools(offline=offline, memory=memory)
    workflows = _build_workflows(tools)
    _register_workflow_tools(tools, workflows)

    conversation = Conversation()
    conversation.add_system(_SYSTEM_PROMPT)

    return Agent(
        llm=llm,
        tools=tools,
        workflows=workflows,
        conversation=conversation,
        memory=memory,
        max_tool_iterations=_store().tool_rounds(),
    )


def build_session_store() -> SessionStore:
    """Construct the session store the GUI persists conversations through."""
    return SessionStore()


def build_dashboard_cache() -> DashboardCache:
    """Construct the per-card cache the dashboard saves/restores its data through."""
    return DashboardCache()


def build_session_titler(*, offline: bool) -> SessionTitler:
    """Construct the auto-namer for chat sessions.

    Online → a lightweight non-think provider on the *text* role's endpoint /
    key. On the default DeepSeek endpoint it uses the cheap `deepseek-v4-flash`
    model; a custom endpoint may not host that model, so it falls back to the
    role's configured model (still non-think). Offline, or when the text role
    has no key, → a provider-less titler that returns a heuristic title (so it
    never raises and never routes through `EchoLLMProvider`).
    """
    if offline:
        return SessionTitler(None)
    cfg = _store().model("text")
    if not cfg.is_configured:
        return SessionTitler(None)
    titler_model = "deepseek-v4-flash" if "deepseek.com" in cfg.base_url else cfg.model
    return SessionTitler(
        DeepSeekProvider(
            api_key=cfg.api_key,
            model=titler_model,
            base_url=cfg.base_url,
            thinking=False,
        )
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


def build_chat_llm(model_key: str, *, offline: bool) -> LLMProvider:
    """Build the chat brain for a role (`text` / `visual`), or Echo when offline.

    The GUI model switcher swaps brains through here. Reads the role's endpoint
    / model / key from the CredentialStore; raises if no key is configured (the
    caller gates the option on `available_chat_models`, so this only fires on a
    misconfiguration). DeepSeek/Kimi are the role defaults but the endpoint is
    whatever the user configured.
    """
    if offline:
        return EchoLLMProvider()
    info = _CHAT_MODELS.get(model_key)
    if info is None:
        raise ValueError(f"unknown chat model: {model_key!r}")
    cfg = _store().model(model_key)
    if not cfg.is_configured:
        raise FileNotFoundError(
            f"{info['label']}尚未配置 API 密钥。请在『设置』中配置模型，"
            "或以离线模式启动。"
        )
    return _build_role_provider(cfg, str(info["provider"]))


def available_chat_models(*, offline: bool) -> list[tuple[str, str]]:
    """`(role, label)` for each model role that has an API key configured.

    Offline → empty (Echo only, no switching). The GUI shows the switcher only
    when at least two roles are available.
    """
    if offline:
        return []
    store = _store()
    return [
        (role, str(info["label"]))
        for role, info in _CHAT_MODELS.items()
        if store.is_model_configured(role)
    ]


def apply_chat_model(agent: Agent, model_key: str, *, offline: bool) -> None:
    """Swap the agent's chat brain in place (mutates `agent.llm`).

    Also gates `doc_read` on the new role: it feeds page images the brain must
    read itself, so it registers only for the vision-capable role (`visual`,
    default Kimi) and is removed on a switch to the text role. The caller resets
    the conversation afterwards (reset-on-switch keeps every conversation
    single-model, so no history mixes the two wire formats).
    """
    agent.llm = build_chat_llm(model_key, offline=offline)
    vision_capable = (not offline) and bool(
        _CHAT_MODELS.get(model_key, {}).get("vision")
    )
    _set_doc_read_registered(agent.tools, vision_capable)


def _set_doc_read_registered(tools: ToolRegistry, enabled: bool) -> None:
    """Add or remove the image-feeding `doc_read` tool (idempotent)."""
    present = "doc_read" in tools
    if enabled and not present:
        tools.register(DocBaseReadTool())
    elif not enabled and present:
        tools.unregister("doc_read")


def _build_llm(*, offline: bool) -> LLMProvider:
    return build_chat_llm(DEFAULT_CHAT_MODEL, offline=offline)


def _build_tools(
    *,
    offline: bool,
    memory: MemoryStore | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClockTool())
    registry.register(MemoryTool(store=memory))
    # The doc base is committed static content with no index to build, so its
    # search registers in every mode (offline included). The `doc_read` image
    # tool is brain-gated and added later by `apply_chat_model` (Kimi only).
    registry.register(DocBaseSearchTool())
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
    return registry


def build_vision_llm() -> KimiProvider | None:
    """Build the visual-role vision provider, or None if it has no key.

    Powers the dashboard's standalone `DocBaseReader` (the chat path instead
    swaps the whole brain to the visual role). Reads the `visual` role's
    endpoint / model / key from the CredentialStore; returns None when it has
    no key configured.
    """
    cfg = _store().model("visual")
    if not cfg.is_configured:
        return None
    return KimiProvider(api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url)


def build_doc_reader() -> DocBaseReader | None:
    """Build the dashboard's standalone doc reader, or None without a Kimi key.

    Encapsulated vision Q&A (render → ask Kimi → text answer) for the 文档库
    dialog's 让 Captain 阅读 button, decoupled from the chat brain so it works
    whichever brain the chat is on. Injected into the dashboard like the other
    GUI services (`memory_learner`); the GUI never constructs it directly.
    """
    vision = build_vision_llm()
    return None if vision is None else DocBaseReader(vision)


_IDENTITY_MEMORY_FIELDS = {
    "name": "identity.name",
    "student_id": "identity.student_id",
    "department": "identity.department",
    "speciality": "identity.speciality",
    "direction": "identity.direction",
    "student_type": "identity.student_type",
    "user_identity": "identity.user_identity",
}


def _sync_pku3b_identity_memory(memory: MemoryStore, *, client_factory=None) -> None:
    """Best-effort startup sync of the student's identity into long-term memory.

    Fetches the public identity summary in-process via ``pypku3b`` (the portal's
    ``getBasicInfo.do``, stripped of 身份证号/住址). Startup must stay robust:
    missing package, expired login, OTP/network errors, or schema changes should
    leave memory unchanged rather than preventing the GUI from opening.

    Sync-once: ``MemoryStore`` persists to disk, so once any identity field is
    stored we skip the blocking portal login on later launches. This call runs
    on the GUI main thread inside ``build_agent``; re-authing the portal every
    launch would freeze startup and risk tripping OTP/rate limits.

    ``client_factory`` is an injectable seam for tests.
    """
    if any(memory.get(key) is not None for key in _IDENTITY_MEMORY_FIELDS.values()):
        return
    creds = stored_credentials(PKU_SECRETS_DIR)
    if creds is None:
        return  # no credentials on disk -> nothing to sync
    factory = client_factory or default_client_factory
    try:
        client = factory(secrets_dir=PKU_SECRETS_DIR, credentials=creds)
        payload = client.get_identity().to_dict()
    except (Pku3bError, OSError):
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


def _build_workflows(tools: ToolRegistry) -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register(HelloWorkflow(tools))
    return registry


def _register_workflow_tools(
    tools: ToolRegistry, workflows: WorkflowRegistry
) -> None:
    """Expose each agent-callable workflow to the LLM as a callable Tool.

    `Agent.turn()` only serializes the ToolRegistry to the LLM, so without
    this a workflow is reachable solely through the GUI workflow button —
    the model never sees it. Wrapping each workflow in a `WorkflowTool` and
    adding it to the same registry puts the workflow in `to_openai_schema()`
    so DeepSeek can start it through the normal tool-call loop. The GUI
    button path (`WorkflowWorker` over `agent.workflows`) is unaffected, and
    recursion is impossible because workflows invoke tools by explicit name,
    never by a workflow name.

    Workflows that set `agent_callable = False` (offline reference stubs like
    `HelloWorkflow`) are skipped: they stay in the `WorkflowRegistry` for the
    loop/tests but never pollute the real agent toolset.
    """
    for workflow in workflows.all():
        if not workflow.agent_callable:
            continue
        tools.register(WorkflowTool(workflow))


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
