"""PyQt6 main window shell."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QThread
from PyQt6.QtWidgets import (
    QDialog,
    QMainWindow,
    QSplitter,
)

from ..core import (
    AgentEvent,
    MemoryLearnService,
    build_agent,
    build_dashboard_cache,
    build_session_store,
    build_session_titler,
    reset_conversation,
    restore_conversation,
)
from .agent_worker import AgentWorker
from .chat_panel import ChatPanel
from .dashboard import DashboardPanel
from .dashboard_worker import DashboardWorker
from .formatters import upcoming_assignments
from .session_history_dialog import SessionHistoryDialog
from .tool_call_worker import run_async
from .workflow_worker import WorkflowWorker, workflow_summary

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_PKU3B = _REPO_ROOT / ".local" / "cargo" / "bin" / "pku3b"
_LOCAL_PLIB = _REPO_ROOT.parent / "plib-cli" / ".venv" / "bin" / "plib"
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

    def __init__(self, *, offline: bool = True, enable_knowledge: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("PKU Captain")
        self.resize(1680, 920)
        self.statusBar().showMessage("正在启动 GUI...")

        fallback_message = ""
        mode_label = "在线模式" if not offline else "离线模式"
        effective_offline = offline
        try:
            agent = build_agent(offline=offline, enable_knowledge=enable_knowledge)
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
        self._dashboard = DashboardPanel(
            mode_label=mode_label, tools=agent.tools, memory_learner=memory_learner
        )
        self._chat_panel = ChatPanel()

        # Per-card download cache: the dashboard paints from saved state on
        # launch, then a silent background refresh updates only the cards whose
        # data changed. `_cached_data` / `_cached_sig` mirror what each card is
        # currently showing (tool-key keyed); `_loading_keys` are the cards put
        # into the spinner state by the in-flight refresh — those must render
        # when their result lands (`_should_render`).
        self._dashboard_cache = build_dashboard_cache()
        self._cached_data: dict[str, object] = {}
        self._cached_sig: dict[str, str] = {}
        self._loading_keys: set[str] = set()

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
                "pku3b_announcements": {"limit": 5},
                "treehole_updates": {"limit": 5},
                "plib_materials": {"action": "quota"},
                "lecture": {"limit": 5},
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
        self._chat_panel.new_chat_requested.connect(self._on_new_chat)
        self._chat_panel.history_requested.connect(self._on_open_history)
        self._dashboard.morning_briefing_requested.connect(self._run_morning_briefing)
        self._dashboard.refresh_requested.connect(self._refresh_dashboard)
        self._dashboard.partial_refresh_requested.connect(self._refresh_dashboard_subset)

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
        self.statusBar().showMessage(f"{mode_label} · 就绪")

    def _send_message(self, text: str) -> None:
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
        elif event.kind == "assistant_delta":
            self._chat_panel.append_assistant_delta(str(event.payload.get("text") or ""))
        elif event.kind == "final":
            self._chat_panel.add_assistant_message(str(event.payload.get("text") or ""))

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

    def _on_new_chat(self) -> None:
        if self._busy:
            return
        self._persist_current_session()
        reset_conversation(self._agent)
        self._chat_panel.clear()
        self._current_session_id = self._session_store.new_id()
        self._current_title = None
        self._session_created_at = _now_iso()
        self._titled = False
        self.setWindowTitle("PKU Captain")
        self.statusBar().showMessage("已开始新对话")

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
        "plib_materials",
        "lecture",
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

    def _start_refresh(self, tool_keys: list[str], *, silent: bool = False) -> None:
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
        loading = key in self._loading_keys
        self._loading_keys.discard(key)
        fresh_sig = _signature(data)
        if not _should_render(loading, self._cached_sig.get(key), fresh_sig):
            return  # cached card unchanged since last save — no repaint
        self._render_dashboard_item(key, data)
        self._cached_data[key] = data
        self._cached_sig[key] = fresh_sig
        self._dashboard_cache.save(key, data)

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
            return
        if key == "treehole_updates" and isinstance(data, dict):
            self._dashboard.set_treehole_updates(data)
            return
        if key == "plib_materials" and isinstance(data, dict):
            self._dashboard.set_plib_materials(data)
            return
        if key == "lecture" and isinstance(data, list):
            self._dashboard.set_lectures(data)
            return
        self._dashboard.set_data(card_key, _format_dashboard_data(key, data))

    def _on_dashboard_item_error(self, key: str, message: str) -> None:
        loading = key in self._loading_keys
        self._loading_keys.discard(key)
        card_key = "schedule" if key == "pku3b_coursetable" else key
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
        self._dashboard.set_refresh_busy(False)
        stamp = datetime.now().strftime("%H:%M:%S")
        self._dashboard.set_updated_text(f"最近刷新：{stamp}")
        self.statusBar().showMessage(f"仪表盘已刷新：{stamp}")

    def _run_morning_briefing(self) -> None:
        QMetaObject.invokeMethod(
            self._workflow_worker,
            "run_workflow",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, "morning_briefing"),
            Q_ARG(dict, {}),
        )

    def _on_workflow_started(self, name: str) -> None:
        if name == "morning_briefing":
            self._dashboard.set_briefing_busy(True)
            self.statusBar().showMessage("正在生成今日简报...")
            self._chat_panel.add_system_message("正在生成今日简报...")

    def _on_workflow_finished(self, name: str, result: object) -> None:
        if name == "morning_briefing":
            self._dashboard.set_briefing_busy(False)
            self._chat_panel.add_assistant_message(workflow_summary(result))
            self.statusBar().showMessage("今日简报已生成")

    def _on_workflow_error(self, name: str, message: str) -> None:
        if name == "morning_briefing":
            self._dashboard.set_briefing_busy(False)
            self._chat_panel.add_system_message(f"今日简报失败：{message}")
            self.statusBar().showMessage("今日简报失败")

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override name.
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
    if key == "plib_materials" and isinstance(data, dict):
        remaining = data.get("download_remaining")
        return "今日剩余下载次数：未知" if remaining is None else f"今日剩余下载次数：{remaining}"
    if key == "lecture" and isinstance(data, list):
        if not data:
            return "近期暂无讲座"
        lines = []
        for item in data[:5]:
            if isinstance(item, dict):
                lines.append(
                    "{time} {title}".format(
                        time=item.get("time", ""),
                        title=item.get("title", "未命名讲座"),
                    ).strip()
                )
        return "\n".join(lines) if lines else "暂无可显示讲座"
    return str(data)


def _startup_diagnostics(*, offline: bool) -> str:
    missing: list[str] = []
    deepseek_key_paths = (
        _REPO_ROOT / "secrets" / "api_keys" / "deepseek_key.txt",
        _REPO_ROOT / "secrets" / "deepseek_key.txt",
    )
    if not any(path.exists() for path in deepseek_key_paths):
        missing.append("DeepSeek key：缺少 secrets/api_keys/deepseek_key.txt")
    if shutil.which("pku3b") is None and not _LOCAL_PKU3B.exists():
        missing.append("pku3b：未在 PATH 中找到")
    elif not _pku3b_configured():
        missing.append("pku3b：已安装，但尚未完成首次登录配置")
    if shutil.which("plib") is None and not _LOCAL_PLIB.exists():
        missing.append("plib：未在 PATH 中找到，P-Lib 搜索不可用")

    if not missing:
        return ""

    prefix = "当前以离线模式运行。" if offline else "在线依赖未完全就绪。"
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
