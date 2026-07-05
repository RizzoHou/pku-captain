"""PyQt6 main window shell."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QThread, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QMainWindow,
    QSplitter,
)

from ..core import (
    DEFAULT_CHAT_MODEL,
    AgentEvent,
    CredentialStore,
    MemoryLearnService,
    VisionRouter,
    apply_chat_model,
    available_chat_models,
    build_agent,
    build_dashboard_cache,
    build_doc_reader,
    build_session_store,
    build_session_titler,
    reset_conversation,
    restore_conversation,
)
from ..core.announcement_history import AnnouncementHistoryStore
from ..core.auto_refresh import (
    AutoRefreshSettings,
    AutoRefreshSettingsStore,
    DashboardChange,
    DashboardDigest,
    MacOSNotifier,
    detect_dashboard_changes,
)
from ..tools.dean_updates import DeanInboxStore
from ..tools.treehole_updates import (
    MIN_NOTIFY_INTERVAL,
    TreeholeHistoryStore,
    TreeholeInboxStore,
    TreeholeNotificationService,
)
from .agent_worker import AgentWorker
from .chat_panel import ChatPanel
from .dashboard import AutoRefreshSettingsDialog, DashboardPanel
from .dashboard_worker import DashboardWorker
from .formatters import upcoming_assignments
from .session_history_dialog import SessionHistoryDialog
from .tool_call_worker import run_async
from .workflow_worker import WorkflowWorker, workflow_summary

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_PKU3B = _REPO_ROOT / ".local" / "cargo" / "bin" / "pku3b"
_TZ = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def _signature(data: object) -> str:
    """Canonical JSON of a card payload, for change detection.

    ``sort_keys`` makes dict ordering irrelevant and serializing through JSON
    absorbs the round-trip type drift a cache reload introduces (a tuple and a
    list both become a JSON array), so re-fetched data that is semantically
    unchanged compares equal to the cached copy and the card is not repainted.
    """
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def _should_render(loading: bool, current_sig: str | None, fresh_sig: str) -> bool:
    """Decide whether a freshly-fetched card payload should be repainted.

    A card we put into the ``加载中...`` state must always render, or it is
    stranded on the spinner forever. Otherwise the cached data is still
    visible, so repaint only when the data actually changed — this is what
    makes a silent startup refresh flicker-free.
    """
    if loading:
        return True
    return current_sig != fresh_sig


class MainWindow(QMainWindow):
    """Top-level window. Layout: dashboard | chat with inline tool calls."""

    def __init__(self, *, offline: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("PKU Captain")
        self.resize(1680, 920)
        self.statusBar().showMessage("正在启动 GUI...")

        fallback_message = ""
        mode_label = "在线模式" if not offline else "离线模式"
        effective_offline = offline
        try:
            agent = build_agent(offline=offline)
        except Exception as exc:  # noqa: BLE001 - any online failure falls back to offline
            agent = build_agent(offline=True)
            effective_offline = True
            mode_label = "离线模式"
            fallback_message = f"在线模式不可用，已切换到离线模式：{exc}"

        self._agent = agent
        # Lets the dashboard 记忆 box split a typed sentence into clean facts
        # via the same LLM the chat uses; degrades to verbatim when offline.
        # Shares agent.memory so dashboard- and chat-learned facts coincide.
        memory_learner = (
            MemoryLearnService(agent.llm, agent.memory)
            if agent.memory is not None
            else None
        )
        # Encapsulated doc reader (Kimi vision Q&A) for the 文档库 dialog's
        # standalone 让 Captain 阅读 — None offline so it never hits the network.
        doc_reader = None if effective_offline else build_doc_reader()
        self._dashboard = DashboardPanel(
            mode_label=mode_label,
            tools=agent.tools,
            memory_learner=memory_learner,
            doc_reader=doc_reader,
            treehole_inbox=TreeholeInboxStore(_REPO_ROOT / "data" / "treehole_inbox.json"),
            treehole_history=TreeholeHistoryStore(
                _REPO_ROOT / "data" / "treehole_history.json"
            ),
            dean_inbox=DeanInboxStore(_REPO_ROOT / "data" / "dean_inbox.json"),
        )
        self._chat_panel = ChatPanel()

        # Per-card download cache: the dashboard paints from saved state on
        # launch, then a silent background refresh updates only the cards whose
        # data changed. `_cached_data` / `_cached_sig` mirror what each card is
        # currently showing (tool-key keyed); `_loading_keys` are the cards put
        # into the spinner state by the in-flight refresh — those must render
        # when their result lands (`_should_render`).
        self._dashboard_cache = build_dashboard_cache()
        self._announcement_history_store = AnnouncementHistoryStore()
        self._dashboard.set_announcement_history(self._announcement_history_store.load())
        self._cached_data: dict[str, object] = {}
        self._cached_sig: dict[str, str] = {}
        self._loading_keys: set[str] = set()
        self._refresh_had_success = False
        self._dashboard_refresh_busy = False
        self._active_refresh_auto = False

        # Keep the 树洞消息 card in step with background auto-checking: while the
        # macOS notifier is enabled, re-poll the treehole card on its interval so
        # new replies surface in-app shortly after their notification, instead of
        # the card staying frozen at its startup snapshot.
        self._notify_service = TreeholeNotificationService()
        self._treehole_sync_timer = QTimer(self)
        self._treehole_sync_timer.timeout.connect(self._on_treehole_sync_tick)
        self._treehole_sync_busy = False
        self._treehole_sync_signals: object = None

        self._auto_refresh_store = AutoRefreshSettingsStore()
        self._auto_refresh_settings = self._auto_refresh_store.load()
        self._auto_refresh_digest = DashboardDigest(
            None if effective_offline else agent.llm
        )
        self._auto_refresh_notifier = MacOSNotifier()
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_tick)
        self._auto_refresh_changes: list[DashboardChange] = []
        self._auto_refresh_baseline_ready = False

        # Multi-session state. The startup session id lives in memory only;
        # nothing is written to disk until the first real user turn, so a
        # window that's opened and closed without chatting leaves no junk file.
        self._effective_offline = effective_offline
        self._session_store = build_session_store()
        self._session_titler = build_session_titler(offline=effective_offline)
        self._busy = False
        self._current_session_id = self._session_store.new_id()
        self._current_title: str | None = None
        self._session_created_at = _now_iso()
        self._titled = False
        self._pending_title_sid = ""

        self._agent_thread = QThread(self)
        self._agent_worker = AgentWorker(agent)
        self._agent_worker.moveToThread(self._agent_thread)
        self._agent_worker.agent_event.connect(self._on_agent_event)
        self._agent_worker.error_occurred.connect(self._on_agent_error)
        self._agent_worker.finished.connect(self._on_turn_finished)
        self._agent_thread.start()

        self._dashboard_thread = QThread(self)
        self._dashboard_worker = DashboardWorker(
            agent.tools,
            {
                "pku3b_coursetable": {},
                "pku3b_assignments": {},
                # Fetch the full announcement list so 历史通知 can show every
                # item reported by pku3b; resolve_dates attaches each item's
                # posted_date so AnnouncementsCard's 最近 section can window to
                # the last month (the rest stay in 历史通知).
                "pku3b_announcements": {"resolve_dates": True},
                "treehole_updates": {"limit": 5},
                "dean_updates": {"limit": 5},
                "plib_materials": {"action": "quota"},
            },
        )
        self._dashboard_worker.moveToThread(self._dashboard_thread)
        self._dashboard_worker.item_loaded.connect(self._on_dashboard_item_loaded)
        self._dashboard_worker.item_error.connect(self._on_dashboard_item_error)
        self._dashboard_worker.finished.connect(self._on_dashboard_refresh_finished)
        self._dashboard_thread.start()

        self._workflow_thread = QThread(self)
        self._workflow_worker = WorkflowWorker(agent.workflows)
        self._workflow_worker.moveToThread(self._workflow_thread)
        self._workflow_worker.started.connect(self._on_workflow_started)
        self._workflow_worker.finished.connect(self._on_workflow_finished)
        self._workflow_worker.error_occurred.connect(self._on_workflow_error)
        self._workflow_thread.start()

        self._chat_panel.send_requested.connect(self._send_message)
        self._chat_panel.stop_requested.connect(self._cancel_turn)
        self._chat_panel.new_chat_requested.connect(self._on_new_chat)
        self._chat_panel.history_requested.connect(self._on_open_history)
        self._chat_panel.model_change_requested.connect(self._on_model_change)

        # Chat-model switcher (DeepSeek ⇄ Kimi K2.6). The active brain drives
        # the context-meter window (256k for Kimi vs 1M for DeepSeek); switching
        # opens a fresh chat (reset-on-switch). Offline shows no switcher.
        self._model_labels = dict(available_chat_models(offline=effective_offline))
        self._model_key: str | None = (
            None if effective_offline else DEFAULT_CHAT_MODEL
        )
        self._chat_panel.set_models(
            list(self._model_labels.items()), self._model_key
        )
        # Auto-switch to Kimi for doc/培养方案 questions asked while on DeepSeek
        # (it reads the page images DeepSeek can't). Heuristic, network-free.
        self._vision_router = VisionRouter()
        self._dashboard.refresh_requested.connect(self._refresh_dashboard)
        self._dashboard.partial_refresh_requested.connect(self._refresh_dashboard_subset)
        self._dashboard.auto_refresh_settings_requested.connect(
            self._open_auto_refresh_settings
        )
        self._dashboard.treehole_settings_changed.connect(self._reconfigure_treehole_sync)
        self._dashboard.model_config_changed.connect(self._on_model_config_changed)
        self._dashboard.agent_settings_changed.connect(self._on_agent_settings_changed)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._dashboard)
        splitter.addWidget(self._chat_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)
        self.setCentralWidget(splitter)
        self._chat_panel.add_system_message(
            f"GUI 已启动：{mode_label}。仪表盘会直接读取工具数据；对话侧栏用于自然语言查询。"
        )
        if fallback_message:
            self._chat_panel.add_system_message(fallback_message)
        diagnostics = _startup_diagnostics(offline=offline)
        if diagnostics:
            self._chat_panel.add_system_message(diagnostics)
        # Paint instantly from the saved cards, then fetch live data in the
        # background and update only the cards that changed.
        self._seed_dashboard_from_cache()
        self._start_refresh([], silent=True)
        self._reconfigure_treehole_sync()
        self._refresh_context_meter()
        self._configure_auto_refresh()
        self.statusBar().showMessage(f"{mode_label} · 就绪")

    def _maybe_auto_switch_for_vision(self, text: str) -> None:
        """Route a doc/培养方案 question into a fresh visual-model chat before the turn.

        Only fires while on the text role with a visual role available. Like a
        manual switch it resets the chat (reset-on-switch); the typed message
        then runs in the fresh visual chat where doc_read can feed it page
        images. No-op on the visual role / offline or for non-doc questions.
        """
        if self._model_key != "text" or "visual" not in self._model_labels:
            return
        if not self._vision_router.needs_doc_base(text):
            return
        try:
            apply_chat_model(self._agent, "visual", offline=self._effective_offline)
        except Exception as exc:  # noqa: BLE001 - stay on the text model on failure
            self._chat_panel.add_system_message(f"自动切换视觉模型失败：{exc}")
            return
        self._model_key = "visual"
        self._chat_panel.set_active_model("visual")
        self._begin_new_session()
        self._chat_panel.add_system_message(
            "检测到培养方案 / 文档相关问题，已自动切换到视觉模型并开启新对话。"
        )

    def _send_message(self, text: str) -> None:
        self._maybe_auto_switch_for_vision(text)
        self._busy = True
        self._chat_panel.add_user_message(text)
        self._chat_panel.set_busy(True)
        self.statusBar().showMessage("Agent 正在处理问题...")
        QMetaObject.invokeMethod(
            self._agent_worker,
            "run_turn",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, text),
        )

    def _cancel_turn(self) -> None:
        """Ask the running turn to stop (chat panel 停止 button).

        Sets the worker's thread-safe cancel flag directly — it must not be a
        queued Qt call, since the worker thread is blocked inside the turn and
        wouldn't drain its event queue until the turn ended. The turn then ends
        with a `final` event, so `_on_turn_finished` clears the busy state.
        """
        if not self._busy:
            return
        self._agent_worker.request_cancel()
        self.statusBar().showMessage("正在停止当前回答...")

    def _on_agent_event(self, event: AgentEvent) -> None:
        if event.kind == "tool_call":
            # Close out the assistant text that preceded this tool call so the
            # next iteration's text becomes its own bubble below the tool rows,
            # instead of overwriting this one.
            self._chat_panel.finalize_assistant_segment()
            self._chat_panel.add_tool_call(
                str(event.payload["id"]),
                str(event.payload["name"]),
                dict(event.payload.get("arguments") or {}),
            )
        elif event.kind == "tool_result":
            self._chat_panel.update_tool_result(
                str(event.payload["id"]),
                str(event.payload["name"]),
                event.payload["result"],
            )
        elif event.kind == "reasoning_delta":
            self._chat_panel.append_reasoning_delta(str(event.payload.get("text") or ""))
        elif event.kind == "assistant_delta":
            self._chat_panel.append_assistant_delta(str(event.payload.get("text") or ""))
        elif event.kind == "context_usage":
            self._refresh_context_meter(event.payload)
        elif event.kind == "final":
            self._chat_panel.add_assistant_message(str(event.payload.get("text") or ""))

    def _refresh_context_meter(self, payload: dict | None = None) -> None:
        """Update the chat context-usage meter.

        With a `payload` (live `context_usage` event) shows the API token count;
        without one (startup, new chat, restored session) shows the agent's
        estimate of the current conversation. Reading the conversation is
        race-free here — callers are all on the GUI thread with no turn running.
        """
        if payload is None:
            payload = self._agent.estimate_context_usage()
        self._chat_panel.set_context_usage(
            int(payload.get("used", 0)),
            int(payload.get("window", 0)),
            estimated=bool(payload.get("estimated", False)),
        )

    def _on_agent_error(self, message: str) -> None:
        self._chat_panel.add_system_message(message)
        self.statusBar().showMessage("Agent 调用失败")

    def _on_turn_finished(self) -> None:
        # Finalize any half-streamed bubble so a turn that ended via error
        # (no `final` event) doesn't leave it dangling into the next turn.
        self._chat_panel.reset_streaming()
        self._chat_panel.set_busy(False)
        self._busy = False
        self.statusBar().showMessage("Agent 回答完成")
        # The turn is done and the worker thread has stopped mutating the
        # conversation, so reading + saving on the GUI thread is race-free.
        self._persist_current_session()
        self._maybe_autoname()

    def _persist_current_session(self) -> None:
        """Write the current conversation through to disk (write-through).

        No-ops until there's at least one user message, so an untouched
        startup/new session never creates a file. Keeps the existing title
        if set, else stamps a network-free provisional one.
        """
        snapshot = self._agent.conversation.snapshot()
        if not any(m.role == "user" for m in snapshot):
            return
        title = self._current_title or self._session_titler.heuristic(snapshot)
        self._session_store.save(
            self._current_session_id,
            messages=snapshot,
            title=title,
            created_at=self._session_created_at,
            offline=self._effective_offline,
        )

    def _maybe_autoname(self) -> None:
        """Fire the flash-model titler once, after the first real exchange.

        Skips error turns (a user message with no assistant reply). The
        title is written to the captured session id — never "current" — so a
        late result can't stamp onto a session the user has since switched
        away from.
        """
        if self._titled:
            return
        snapshot = self._agent.conversation.snapshot()
        if not any(m.role == "user" for m in snapshot):
            return
        if not any(m.role == "assistant" and m.content.strip() for m in snapshot):
            return
        self._titled = True  # optimistic: fire exactly once per session
        self._pending_title_sid = self._current_session_id
        run_async(
            lambda: self._session_titler.generate(snapshot),
            on_done=self._on_title_ready,
            on_error=self._on_title_error,
        )

    def _on_title_ready(self, title: object) -> None:
        text = str(title).strip()
        if not text:
            return
        sid = self._pending_title_sid
        self._session_store.update_title(sid, text)
        if sid == self._current_session_id:
            self._current_title = text
            self.setWindowTitle(f"PKU Captain · {text}")

    def _on_title_error(self, _message: str) -> None:
        # Titling is best-effort; the provisional title already on disk stays.
        pass

    def _begin_new_session(self) -> None:
        """Persist the current chat and reset to a fresh, system-seeded one.

        Shared by the ＋新对话 button and the model switcher (reset-on-switch).
        Refreshes the context meter so a model swap immediately reflects the new
        brain's window (e.g. 256k for Kimi).
        """
        self._persist_current_session()
        reset_conversation(self._agent)
        self._chat_panel.clear()
        self._refresh_context_meter()
        self._current_session_id = self._session_store.new_id()
        self._current_title = None
        self._session_created_at = _now_iso()
        self._titled = False
        self.setWindowTitle("PKU Captain")

    def _on_new_chat(self) -> None:
        if self._busy:
            return
        self._begin_new_session()
        self.statusBar().showMessage("已开始新对话")

    def _on_model_change(self, model_key: str) -> None:
        """Switch the chat brain (DeepSeek ⇄ Kimi K2.6); reset-on-switch.

        No-ops while a turn is in flight (the conversation must not swap under
        the worker thread). On success swaps `agent.llm`, opens a fresh chat,
        and the context meter re-reads the new brain's window. The dashboard's
        own LLM helpers (digest / memory-learn) keep their original provider —
        they are independent of the chat brain.
        """
        if self._busy:
            # Can't switch mid-turn; snap the combo back to the active brain.
            if self._model_key is not None:
                self._chat_panel.set_active_model(self._model_key)
            self.statusBar().showMessage("正在回答，请稍后再切换模型")
            return
        if model_key == self._model_key:
            return
        try:
            apply_chat_model(self._agent, model_key, offline=self._effective_offline)
        except Exception as exc:  # noqa: BLE001 - surface and revert the combo
            self._chat_panel.add_system_message(f"切换模型失败：{exc}")
            if self._model_key is not None:
                self._chat_panel.set_active_model(self._model_key)
            return
        self._model_key = model_key
        label = self._model_labels.get(model_key, model_key)
        self._begin_new_session()
        self._chat_panel.add_system_message(f"已切换到 {label}，并开启新对话。")
        self.statusBar().showMessage(f"已切换到 {label}")

    def _on_model_config_changed(self) -> None:
        """Apply a 设置 → 模型配置 edit to the running chat brain, no restart.

        The account dialog persists the new per-role endpoint / model / key and
        emits the `models` sentinel; this rebuilds the *active* role's brain from
        that on-disk config so the next turn uses it, and refreshes the switcher
        + context meter. Unlike a manual switch it keeps the conversation — a
        config edit on the same role is not a role swap. The exception is when
        the active role just lost its key: it then falls back to a configured
        role, which (like `_on_model_change`) resets the chat.
        """
        if self._effective_offline:
            # Offline runs the Echo brain; there is no live model to rebuild.
            # The edit is saved and takes effect on the next online launch.
            self.statusBar().showMessage("模型配置已保存，将在联网启动后生效")
            return
        if self._busy:
            # Never swap the brain under an in-flight turn (mirrors
            # `_on_model_change`). The saved edit applies on the next switch /
            # restart instead.
            self.statusBar().showMessage("正在回答，模型配置将在切换模型或重启后生效")
            return
        new_labels = dict(available_chat_models(offline=False))
        # Keep the active role if it still has a key, else fall back to a
        # configured one so the chat always has a usable brain.
        if self._model_key in new_labels:
            target = self._model_key
        elif DEFAULT_CHAT_MODEL in new_labels:
            target = DEFAULT_CHAT_MODEL
        else:
            target = next(iter(new_labels), DEFAULT_CHAT_MODEL)
        switched = target != self._model_key
        try:
            apply_chat_model(self._agent, target, offline=False)
        except Exception as exc:  # noqa: BLE001 - keep the current brain, surface it
            self._chat_panel.add_system_message(f"应用模型配置失败：{exc}")
            return
        self._model_labels = new_labels
        self._model_key = target
        self._chat_panel.set_models(list(new_labels.items()), target)
        if switched:
            # The previously-active role lost its key; a different brain resets.
            self._begin_new_session()
            label = new_labels.get(target, target)
            self._chat_panel.add_system_message(
                f"原模型配置已失效，已切换到 {label} 并开启新对话。"
            )
            self.statusBar().showMessage(f"已切换到 {label}")
        else:
            # Same role, new endpoint / model / key: keep history, refresh meter.
            self._refresh_context_meter()
            self._chat_panel.add_system_message("已更新模型配置并即时生效。")
            self.statusBar().showMessage("模型配置已更新")

    def _on_agent_settings_changed(self) -> None:
        """Apply a 设置 → 对话设置 edit (tool-round limit) to the live agent.

        The dialog persisted the new limit and emitted the `tool_rounds`
        sentinel; re-read it and set `max_tool_iterations` on the running agent
        so the next turn honours it (no restart). Applies to any brain, so —
        unlike the model sentinel — it needs no offline guard. A mid-turn edit
        takes effect on the following turn (the current turn's iteration count
        is already fixed), so there is no busy guard either.
        """
        rounds = CredentialStore().tool_rounds()
        self._agent.max_tool_iterations = rounds
        self.statusBar().showMessage(f"已更新工具调用轮数上限：{rounds}")

    def _on_open_history(self) -> None:
        if self._busy:
            return
        self._persist_current_session()
        dialog = SessionHistoryDialog(
            self._session_store, current_id=self._current_session_id, parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_id:
            return
        record = self._session_store.load(dialog.selected_id)
        if record is None:
            self.statusBar().showMessage("会话加载失败")
            return
        restore_conversation(self._agent, record.get("messages", []))
        self._chat_panel.load_history(self._agent.conversation.snapshot())
        self._refresh_context_meter()
        self._current_session_id = str(record.get("id", dialog.selected_id))
        self._current_title = record.get("title") or None
        self._session_created_at = str(record.get("created_at") or _now_iso())
        self._titled = True
        display_title = self._current_title or "历史会话"
        self.setWindowTitle(f"PKU Captain · {display_title}")
        self.statusBar().showMessage(f"已打开会话：{display_title}")

    # Tool keys the dashboard refreshes, in `DashboardWorker._tool_args` terms.
    # Only `pku3b_coursetable` differs from its card key (`schedule`).
    _ALL_TOOL_KEYS = (
        "pku3b_coursetable",
        "pku3b_assignments",
        "pku3b_announcements",
        "treehole_updates",
        "dean_updates",
        "plib_materials",
    )

    def _seed_dashboard_from_cache(self) -> None:
        """Paint each card from its saved download, before any live fetch.

        Renders raw cached payloads and records what each card now shows so the
        background refresh can skip the cards whose data is unchanged. A
        malformed cache entry is skipped (never crashes startup) and gets
        repainted by the refresh once live data arrives.
        """
        for key, data in self._dashboard_cache.load_all().items():
            try:
                self._render_dashboard_item(key, data)
            except Exception:  # noqa: BLE001 - a bad cache entry must not abort startup
                continue
            self._cached_data[key] = data
            self._cached_sig[key] = _signature(data)
        stamp = self._dashboard_cache.newest_timestamp()
        if stamp:
            self._dashboard.set_updated_text(f"上次保存：{stamp}")

    def _refresh_dashboard(self) -> None:
        """Refresh every dashboard card (header 刷新 button)."""
        self._start_refresh([])

    def _refresh_dashboard_subset(self, keys: list) -> None:
        """Refresh only the given tools, so a single card's refresh button does
        not trigger a full-dashboard reload."""
        self._start_refresh([str(key) for key in keys])

    def _start_refresh(
        self,
        tool_keys: list[str],
        *,
        silent: bool = False,
        auto_notify: bool = False,
    ) -> None:
        """Reload `tool_keys` (empty list means all) and scope the worker to the
        same set.

        `silent` is the startup pass: a card that already shows cached data
        keeps it (no spinner) and is repainted only if its fresh data differs.
        An explicit refresh (`silent=False`, header / per-card buttons) always
        shows the spinner and always repaints, so a click gives visible
        feedback even when nothing changed. A card put into the loading state
        is recorded in `_loading_keys`, which guarantees it gets rendered when
        its result arrives (`_should_render`).
        """
        if self._dashboard_refresh_busy:
            return
        self._dashboard_refresh_busy = True
        self._active_refresh_auto = auto_notify
        self._auto_refresh_changes = []
        self._refresh_had_success = False
        if not auto_notify:
            self._dashboard.set_refresh_busy(True)
            self.statusBar().showMessage("正在刷新仪表盘...")
            for name in tool_keys or self._ALL_TOOL_KEYS:
                if silent and name in self._cached_sig:
                    continue  # keep cached content visible, no spinner flicker
                card_key = "schedule" if name == "pku3b_coursetable" else name
                self._dashboard.set_loading(card_key)
                self._loading_keys.add(name)
        # Read GUI widgets (the OTP field) here, on the GUI thread, and hand
        # the snapshot to the worker — the worker must never touch widgets.
        dynamic_args = {"pku3b_coursetable": self._dashboard_args("pku3b_coursetable")}
        QMetaObject.invokeMethod(
            self._dashboard_worker,
            "refresh",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(dict, dynamic_args),
            Q_ARG(list, list(tool_keys)),
        )

    def _on_dashboard_item_loaded(self, key: str, data: object) -> None:
        self._refresh_had_success = True  # a live fetch landed (even if unchanged)
        loading = key in self._loading_keys
        self._loading_keys.discard(key)
        fresh_sig = _signature(data)
        if self._active_refresh_auto and key in self._cached_data:
            self._auto_refresh_changes.extend(
                detect_dashboard_changes(key, self._cached_data[key], data)
            )
        if not _should_render(loading, self._cached_sig.get(key), fresh_sig):
            return  # cached card unchanged since last save — no repaint
        self._render_dashboard_item(key, data)
        self._cached_data[key] = data
        self._cached_sig[key] = fresh_sig
        try:
            self._dashboard_cache.save(key, data)
        except Exception:  # noqa: BLE001 - a cache-write surprise must not crash the slot
            pass

    def _render_dashboard_item(self, key: str, data: object) -> None:
        """Dispatch one card's raw payload to its setter (no cache write)."""
        card_key = "schedule" if key == "pku3b_coursetable" else key
        if key == "pku3b_coursetable" and isinstance(data, dict):
            self._dashboard.set_schedule(data)
            return
        if key == "pku3b_assignments" and isinstance(data, dict):
            self._dashboard.set_assignments(data)
            return
        if key == "pku3b_announcements" and isinstance(data, dict):
            self._dashboard.set_announcements(data)
            self._announcement_history_store.save(self._dashboard.announcement_history())
            return
        if key == "treehole_updates" and isinstance(data, dict):
            self._dashboard.set_treehole_updates(data)
            return
        if key == "dean_updates" and isinstance(data, dict):
            self._dashboard.set_dean_updates(data)
            return
        if key == "plib_materials" and isinstance(data, dict):
            self._dashboard.set_plib_materials(data)
            return
        self._dashboard.set_data(card_key, _format_dashboard_data(key, data))

    def _on_dashboard_item_error(self, key: str, message: str) -> None:
        loading = key in self._loading_keys
        self._loading_keys.discard(key)
        card_key = "schedule" if key == "pku3b_coursetable" else key
        if self._active_refresh_auto:
            return
        if key in self._cached_data:
            # Keep the last-good cached download visible rather than wiping a
            # card to an error. An explicit refresh blanked it to the spinner,
            # so repaint the cache; a silent pass never touched it.
            if loading:
                self._render_dashboard_item(key, self._cached_data[key])
            self.statusBar().showMessage(f"{card_key} 刷新失败，继续显示缓存：{message}")
            return
        self._dashboard.set_error(card_key, message)

    def _dashboard_args(self, name: str) -> dict[str, object]:
        if name == "pku3b_coursetable":
            otp_code = self._dashboard.otp_code()
            return {"otp_code": otp_code} if otp_code else {}
        return {}

    def _on_dashboard_refresh_finished(self) -> None:
        was_auto = self._active_refresh_auto
        self._dashboard_refresh_busy = False
        self._active_refresh_auto = False
        if was_auto:
            self._finish_auto_refresh()
            return
        self._dashboard.set_refresh_busy(False)
        if not self._refresh_had_success:
            # Every card errored (e.g. offline) and is showing stale cache —
            # leave the "上次保存" label rather than claim a fresh refresh.
            self.statusBar().showMessage("仪表盘刷新失败，继续显示缓存")
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self._dashboard.set_updated_text(f"最近刷新：{stamp}")
        self.statusBar().showMessage(f"仪表盘已刷新：{stamp}")

    # --- dashboard auto-refresh ----------------------------------------------
    def _configure_auto_refresh(self) -> None:
        settings = self._auto_refresh_settings
        interval = max(60, int(settings.interval_seconds))
        self._auto_refresh_timer.setInterval(interval * 1000)
        if settings.enabled:
            self._auto_refresh_timer.start()
            label = f"自动刷新 {int(interval / 60)}m"
        else:
            self._auto_refresh_timer.stop()
            label = "自动刷新关"
        self._dashboard.set_auto_refresh_text(label)

    def _open_auto_refresh_settings(self) -> None:
        settings = self._auto_refresh_settings
        dialog = AutoRefreshSettingsDialog(
            enabled=settings.enabled,
            interval_seconds=settings.interval_seconds,
            notify_enabled=settings.notify_enabled,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.settings()
        self._auto_refresh_settings = AutoRefreshSettings(
            enabled=bool(values["enabled"]),
            interval_seconds=int(values["interval_seconds"]),
            notify_enabled=bool(values["notify_enabled"]),
        )
        self._auto_refresh_store.save(self._auto_refresh_settings)
        self._configure_auto_refresh()
        state = "已开启" if self._auto_refresh_settings.enabled else "已关闭"
        self.statusBar().showMessage(f"自动刷新{state}")

    def _on_auto_refresh_tick(self) -> None:
        if self._dashboard_refresh_busy:
            return
        self._start_refresh([], silent=True, auto_notify=True)

    def _finish_auto_refresh(self) -> None:
        if not self._refresh_had_success:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self._dashboard.set_updated_text(f"后台刷新：{stamp}")
        changes = list(self._auto_refresh_changes)
        self._auto_refresh_changes = []
        if not self._auto_refresh_baseline_ready:
            self._auto_refresh_baseline_ready = True
            return
        if not changes or not self._auto_refresh_settings.notify_enabled:
            return
        digest = self._auto_refresh_digest.summarize(changes)
        if not digest:
            return
        self._chat_panel.add_system_message(f"后台自动刷新发现新变化：\n{digest}")
        self._auto_refresh_notifier.notify(digest)

    # --- treehole auto-sync ---------------------------------------------------
    def _reconfigure_treehole_sync(self) -> None:
        """Start/stop the treehole auto-sync timer to match the notifier.

        The timer runs only when the treehole tool is registered (online) and
        background auto-checking is enabled, ticking at the notifier's interval
        so the in-app card tracks what the notifier surfaces. Re-read on startup
        and whenever the treehole dialog (which hosts the notify settings)
        closes, so an enable/disable/interval change takes effect immediately.
        """
        active = (
            "treehole_updates" in self._agent.tools
            and self._notify_service.is_supported()
            and self._notify_service.is_enabled()
            and self._notify_service.is_logged_in()
        )
        if active:
            interval = max(MIN_NOTIFY_INTERVAL, self._notify_service.get_interval())
            self._treehole_sync_timer.setInterval(interval * 1000)
            if not self._treehole_sync_timer.isActive():
                self._treehole_sync_timer.start()
        else:
            self._treehole_sync_timer.stop()

    def _on_treehole_sync_tick(self) -> None:
        """Quietly re-poll the treehole card off the GUI thread.

        Goes through ``run_async`` rather than the dashboard refresh worker so it
        does not flicker the global 刷新 button or spam the status bar every
        interval; the result is merged into the accumulating inbox. A poll in
        flight (or a transient error) is skipped — the next tick catches up.
        """
        if self._treehole_sync_busy:
            return
        tool = self._agent.tools.find("treehole_updates")
        if tool is None:
            return
        self._treehole_sync_busy = True
        self._treehole_sync_signals = run_async(
            lambda: tool.invoke({"limit": 5}),
            on_done=self._on_treehole_sync_done,
            on_error=self._on_treehole_sync_error,
        )

    def _on_treehole_sync_done(self, result: object) -> None:
        self._treehole_sync_busy = False
        data = getattr(result, "data", None)
        if getattr(result, "success", False) and isinstance(data, dict):
            self._dashboard.set_treehole_updates(data)

    def _on_treehole_sync_error(self, message: str) -> None:
        self._treehole_sync_busy = False

    # Generic GUI workflow-launch handlers, wired to the retained WorkflowWorker.
    # No workflow is launched via the button today (the morning briefing was
    # removed), but the path stays functional for any future GUI workflow.
    def _on_workflow_started(self, name: str) -> None:
        self.statusBar().showMessage(f"正在运行 {name}...")

    def _on_workflow_finished(self, name: str, result: object) -> None:
        self._chat_panel.add_assistant_message(workflow_summary(result))
        self.statusBar().showMessage(f"{name} 已完成")

    def _on_workflow_error(self, name: str, message: str) -> None:
        self._chat_panel.add_system_message(f"{name} 失败：{message}")
        self.statusBar().showMessage(f"{name} 失败")

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name.
        self._auto_refresh_timer.stop()
        self._treehole_sync_timer.stop()
        self._persist_current_session()
        self._agent_thread.quit()
        self._dashboard_thread.quit()
        self._workflow_thread.quit()
        self._agent_thread.wait(3000)
        self._dashboard_thread.wait(3000)
        self._workflow_thread.wait(3000)
        super().closeEvent(event)


def _format_dashboard_data(key: str, data: object) -> str:
    if key == "pku3b_assignments" and isinstance(data, dict):
        assignments = data.get("assignments", [])
        if not assignments:
            return "暂无未完成作业"
        visible = upcoming_assignments(assignments)
        lines = []
        for item in visible[:5]:
            if isinstance(item, dict):
                lines.append(
                    "{course}：{title}（{deadline}）".format(
                        course=item.get("course_name", "未知课程"),
                        title=item.get("title", "未命名作业"),
                        deadline=item.get("deadline_raw")
                        or item.get("deadline_iso")
                        or "时间未知",
                    )
                )
        return "\n".join(lines) if lines else "暂无可显示作业"
    if key == "pku3b_announcements" and isinstance(data, dict):
        announcements = data.get("announcements", [])
        if not announcements:
            return "暂无课程通知"
        lines = []
        for item in announcements[:5]:
            if isinstance(item, dict):
                lines.append(
                    "{course}：{title}".format(
                        course=item.get("course", "未知课程"),
                        title=item.get("title", "未命名通知"),
                    )
                )
        return "\n".join(lines) if lines else "暂无可显示通知"
    if key == "treehole_updates" and isinstance(data, dict):
        return str(data.get("message") or "暂无树洞新回复")
    if key == "dean_updates" and isinstance(data, dict):
        return str(data.get("message") or "暂无教务部新内容")
    if key == "plib_materials" and isinstance(data, dict):
        remaining = data.get("download_remaining")
        return "今日剩余下载次数：未知" if remaining is None else f"今日剩余下载次数：{remaining}"
    return str(data)


def _startup_diagnostics(*, offline: bool) -> str:
    missing: list[str] = []
    if not CredentialStore().is_model_configured("text"):
        missing.append("文本模型：尚未配置 API 密钥（点击右上角『设置』→ 模型配置）")
    if shutil.which("pku3b") is None and not _LOCAL_PKU3B.exists():
        missing.append("pku3b：未在 PATH 中找到")
    elif not _pku3b_configured():
        missing.append("pku3b：已安装，但尚未完成首次登录配置")

    if not missing:
        return ""

    prefix = (
        "当前以离线模式运行。点击右上角『设置』即可登录北大统一身份、PKUHub 并配置对话模型。"
        if offline
        else "在线依赖未完全就绪。"
    )
    return prefix + "\n" + "\n".join(f"- {item}" for item in missing)


def _pku3b_configured() -> bool:
    # pku3b stores its config under a reverse-domain dir on macOS
    # (~/Library/Application Support/org.sshwy.pku3b/cfg.toml) and under
    # ~/.config/pku3b on Linux. Check for the cfg.toml file itself rather than
    # bare directory existence, since the dir can exist before first login.
    support = Path.home() / "Library" / "Application Support"
    config_files = [
        Path.home() / ".config" / "pku3b" / "cfg.toml",
        support / "pku3b" / "cfg.toml",
        support / "org.sshwy.pku3b" / "cfg.toml",
    ]
    return any(f.is_file() for f in config_files)
