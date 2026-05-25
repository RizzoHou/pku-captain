"""PyQt6 main window shell."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QThread
from PyQt6.QtWidgets import (
    QMainWindow,
    QSplitter,
)

from ..core import AgentEvent, build_agent
from .agent_worker import AgentWorker
from .chat_panel import ChatPanel
from .dashboard import DashboardPanel
from .dashboard_worker import DashboardWorker
from .formatters import upcoming_assignments
from .tool_trace_panel import ToolTracePanel
from .workflow_worker import WorkflowWorker, workflow_summary

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_PKU3B = _REPO_ROOT / ".local" / "cargo" / "bin" / "pku3b"


class MainWindow(QMainWindow):
    """Top-level window. Layout: dashboard | chat sidebar | tool-call panel."""

    def __init__(self, *, offline: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("PKU Captain")
        self.resize(1500, 900)
        self.statusBar().showMessage("正在启动 GUI...")

        fallback_message = ""
        mode_label = "在线模式" if not offline else "离线模式"
        try:
            agent = build_agent(offline=offline, skip_knowledge=True)
        except FileNotFoundError as exc:
            agent = build_agent(offline=True)
            mode_label = "离线模式"
            fallback_message = f"在线模式不可用，已切换到离线模式：{exc}"

        self._dashboard = DashboardPanel(mode_label=mode_label)
        self._chat_panel = ChatPanel()
        self._tool_trace_panel = ToolTracePanel()

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
                "weather": {},
                "lecture": {"limit": 5},
            },
            args_provider=self._dashboard_args,
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
        self._dashboard.morning_briefing_requested.connect(self._run_morning_briefing)
        self._dashboard.refresh_requested.connect(self._refresh_dashboard)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._dashboard)
        splitter.addWidget(self._chat_panel)
        splitter.addWidget(self._tool_trace_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        self.setCentralWidget(splitter)
        self._chat_panel.add_system_message(
            f"GUI 已启动：{mode_label}。仪表盘会直接读取工具数据；对话侧栏用于自然语言查询。"
        )
        if fallback_message:
            self._chat_panel.add_system_message(fallback_message)
        diagnostics = _startup_diagnostics(offline=offline)
        if diagnostics:
            self._chat_panel.add_system_message(diagnostics)
        self._refresh_dashboard()
        self.statusBar().showMessage(f"{mode_label} · 就绪")

    def _send_message(self, text: str) -> None:
        self._chat_panel.add_user_message(text)
        self._tool_trace_panel.clear()
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
            self._tool_trace_panel.add_tool_call(
                str(event.payload["id"]),
                str(event.payload["name"]),
                dict(event.payload.get("arguments") or {}),
            )
        elif event.kind == "tool_result":
            self._tool_trace_panel.update_tool_result(
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
        self._chat_panel.set_busy(False)
        self.statusBar().showMessage("Agent 回答完成")

    def _refresh_dashboard(self) -> None:
        self._dashboard.set_refresh_busy(True)
        self.statusBar().showMessage("正在刷新仪表盘...")
        for key in (
            "schedule",
            "pku3b_assignments",
            "pku3b_announcements",
            "weather",
            "lecture",
        ):
            self._dashboard.set_loading(key)
        QMetaObject.invokeMethod(
            self._dashboard_worker,
            "refresh",
            Qt.ConnectionType.QueuedConnection,
        )

    def _on_dashboard_item_loaded(self, key: str, data: object) -> None:
        card_key = "schedule" if key == "pku3b_coursetable" else key
        if key == "pku3b_coursetable" and isinstance(data, dict):
            self._dashboard.set_schedule(data)
            return
        if key == "pku3b_assignments" and isinstance(data, dict):
            self._dashboard.set_assignments(data)
            return
        if key == "weather" and isinstance(data, dict):
            self._dashboard.set_weather(data)
            return
        self._dashboard.set_data(card_key, _format_dashboard_data(key, data))

    def _on_dashboard_item_error(self, key: str, message: str) -> None:
        card_key = "schedule" if key == "pku3b_coursetable" else key
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
        self._agent_thread.quit()
        self._dashboard_thread.quit()
        self._workflow_thread.quit()
        self._agent_thread.wait(3000)
        self._dashboard_thread.wait(3000)
        self._workflow_thread.wait(3000)
        super().closeEvent(event)


def _format_dashboard_data(key: str, data: object) -> str:
    if key == "weather" and isinstance(data, dict):
        return "{location}：{desc}，{temp}°C，体感 {feels}°C".format(
            location=data.get("location", "未知地点"),
            desc=data.get("weather_description", "未知"),
            temp=data.get("temperature_c", "?"),
            feels=data.get("apparent_temperature_c", "?"),
        )
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
    if not (_REPO_ROOT / "secrets" / "deepseek_key.txt").exists():
        missing.append("DeepSeek key：缺少 secrets/deepseek_key.txt")
    if shutil.which("pku3b") is None and not _LOCAL_PKU3B.exists():
        missing.append("pku3b：未在 PATH 中找到")
    elif not _pku3b_configured():
        missing.append("pku3b：已安装，但尚未完成首次登录配置")

    if not missing:
        return ""

    prefix = "当前以离线模式运行。" if offline else "在线依赖未完全就绪。"
    return prefix + "\n" + "\n".join(f"- {item}" for item in missing)


def _pku3b_configured() -> bool:
    config_roots = [
        Path.home() / ".config" / "pku3b",
        Path.home() / "Library" / "Application Support" / "pku3b",
    ]
    return any(root.exists() for root in config_roots)
