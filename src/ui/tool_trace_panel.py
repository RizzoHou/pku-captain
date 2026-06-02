"""Visible tool-call trace panel for AgentEvent rendering."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .formatters import upcoming_assignments


class ToolTracePanel(QWidget):
    """Render tool calls and their results as a chronological trace."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ToolTracePanel")
        self.setMinimumWidth(260)
        self._rows: dict[str, ToolTraceRow] = {}

        self._trace_layout = QVBoxLayout()
        self._trace_layout.setSpacing(8)
        self._trace_layout.addStretch()

        trace_host = QWidget()
        trace_host.setLayout(self._trace_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(trace_host)
        self._scroll = scroll

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        title = QLabel("工具调用")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addWidget(scroll, 1)

    def add_tool_call(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        row = ToolTraceRow()
        row.set_trace(name, "调用中", _to_json(arguments), "pending")
        self._rows[call_id] = row
        self._trace_layout.insertWidget(self._trace_layout.count() - 1, row)
        self._scroll_to_bottom()

    def update_tool_result(self, call_id: str, name: str, result: Any) -> None:
        row = self._rows.get(call_id)
        if row is None:
            row = ToolTraceRow()
            self._rows[call_id] = row
            self._trace_layout.insertWidget(self._trace_layout.count() - 1, row)

        success = bool(getattr(result, "success", False))
        body = getattr(result, "data", None) if success else getattr(result, "error", None)
        status = "成功" if success else "失败"
        role = "success" if success else "error"
        row.set_trace(name, status, _format_tool_result(name, body), role)
        self._scroll_to_bottom()

    def clear(self) -> None:
        while self._trace_layout.count() > 1:
            item = self._trace_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

    def _scroll_to_bottom(self) -> None:
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())


class ToolTraceRow(QFrame):
    """One collapsible tool-call row."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ToolTraceRow")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._expanded = False
        self._role = "pending"

        self._name_label = QLabel("")
        self._name_label.setObjectName("ToolTraceName")
        self._name_label.setWordWrap(True)
        self._status_label = QLabel("")
        self._status_label.setObjectName("ToolTraceStatus")

        self._toggle_button = QPushButton("展开")
        self._toggle_button.setObjectName("InlineToggleButton")
        self._toggle_button.clicked.connect(self._toggle_detail)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(8)
        meta.addWidget(self._status_label, 1)
        meta.addWidget(self._toggle_button, 0)

        self._detail_label = QLabel("")
        self._detail_label.setObjectName("ToolTraceDetail")
        self._detail_label.setTextInteractionFlags(
            self._detail_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail_label.setWordWrap(True)
        self._detail_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self._name_label)
        layout.addLayout(meta)
        layout.addWidget(self._detail_label)

    def set_trace(self, name: str, status: str, detail: str, role: str) -> None:
        self._role = role
        self.setProperty("traceRole", role)
        self.style().unpolish(self)
        self.style().polish(self)
        self._name_label.setText(name)
        self._status_label.setText(status)
        self._detail_label.setText(detail)
        self._apply_expanded()

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    def _apply_expanded(self) -> None:
        self._detail_label.setVisible(self._expanded)
        self._toggle_button.setText("收起" if self._expanded else "展开")


def _format_tool_result(name: str, body: Any) -> str:
    if name == "pku3b_assignments" and isinstance(body, dict):
        return _format_assignments(body)
    if name == "pku3b_announcements" and isinstance(body, dict):
        return _format_announcements(body)
    if name == "pku3b_coursetable" and isinstance(body, dict):
        return _format_course_table(body)
    if name == "plib_materials" and isinstance(body, dict):
        return _format_plib_materials(body)
    if name == "treehole_updates" and isinstance(body, dict):
        return _format_treehole_updates(body)
    if name == "weather" and isinstance(body, dict):
        return _format_weather(body)
    if name == "lecture" and isinstance(body, list):
        return _format_lectures(body)
    return _to_json(body)


def _format_assignments(data: dict[str, Any]) -> str:
    items = data.get("assignments")
    if not isinstance(items, list) or not items:
        return "未返回作业。"

    upcoming = upcoming_assignments(items)
    if not upcoming:
        return "暂无未完成作业。"

    lines = [f"共 {len(upcoming)} 项未完成作业，展示最近 5 项："]
    for item in upcoming[:5]:
        lines.append(
            "- {course}：{title}（{deadline}）".format(
                course=item.get("course_name", "未知课程"),
                title=item.get("title", "未命名作业"),
                deadline=item.get("deadline_raw") or item.get("deadline_iso") or "时间未知",
            )
        )
    return "\n".join(lines)


def _format_announcements(data: dict[str, Any]) -> str:
    items = data.get("announcements")
    if not isinstance(items, list) or not items:
        return "暂无课程通知。"

    lines = [f"返回 {len(items)} 条课程通知，展示前 5 条："]
    for item in items[:5]:
        if isinstance(item, dict):
            lines.append(
                "- {course}：{title}".format(
                    course=item.get("course", "未知课程"),
                    title=item.get("title", "未命名通知"),
                )
            )
    return "\n".join(lines)


def _format_weather(data: dict[str, Any]) -> str:
    return "{location}：{desc}，{temp}°C，体感 {feels}°C，湿度 {humidity}%".format(
        location=data.get("location", "未知地点"),
        desc=data.get("weather_description", "未知"),
        temp=data.get("temperature_c", "?"),
        feels=data.get("apparent_temperature_c", "?"),
        humidity=data.get("humidity_percent", "?"),
    )


def _format_treehole_updates(data: dict[str, Any]) -> str:
    message = str(data.get("message") or "暂无树洞新回复")
    updates = data.get("updates")
    if not isinstance(updates, list) or not updates:
        return message
    lines = [message]
    for item in updates[:5]:
        if isinstance(item, dict):
            lines.append(
                "- #{pid}：新增 {delta} 条".format(
                    pid=item.get("pid", "?"),
                    delta=item.get("delta", 0),
                )
            )
    return "\n".join(lines)


def _format_plib_materials(data: dict[str, Any]) -> str:
    if "download_remaining" in data:
        return f"P-Lib 今日剩余下载次数：{data.get('download_remaining')}"
    results = data.get("results")
    if isinstance(results, list):
        if not results:
            return "P-Lib 没有找到匹配资料。"
        lines = [f"P-Lib 返回 {len(results)} 条资料，展示前 5 条："]
        for item in results[:5]:
            if isinstance(item, dict):
                lines.append(
                    "- #{id} {title}（{type}，下载 {downloads}）".format(
                        id=item.get("id", "?"),
                        title=item.get("title", "未命名资料"),
                        type=item.get("type", "类型未知"),
                        downloads=item.get("downloads", "?"),
                    )
                )
        return "\n".join(lines)
    if "title" in data:
        return "#{id} {title}\n{desc}".format(
            id=data.get("id", "?"),
            title=data.get("title", "未命名资料"),
            desc=data.get("description") or data.get("course") or "",
        ).strip()
    if "downloads" in data:
        return f"P-Lib 已下载 {len(data.get('downloads') or [])} 个文件。"
    return _to_json(data)


def _format_course_table(data: dict[str, Any]) -> str:
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return "暂无课表数据。"
    lines = [f"返回 {len(blocks)} 个课程时间块，展示前 6 个："]
    for item in blocks[:6]:
        if isinstance(item, dict):
            start = item.get("start_slot", "?")
            end = item.get("end_slot", start)
            slot = f"第{start}节" if start == end else f"第{start}-{end}节"
            lines.append(
                "- {day} {slot}：{title}".format(
                    day=item.get("day_name", ""),
                    slot=slot,
                    title=item.get("title", "未命名课程"),
                )
            )
    return "\n".join(lines)


def _format_lectures(items: list[Any]) -> str:
    if not items:
        return "近期暂无讲座。"
    lines = [f"返回 {len(items)} 场讲座，展示前 5 场："]
    for item in items[:5]:
        if isinstance(item, dict):
            lines.append(
                "- {time} {title}（{location}）".format(
                    time=item.get("time", ""),
                    title=item.get("title", "未命名讲座"),
                    location=item.get("location", "地点待定"),
                ).strip()
            )
    return "\n".join(lines)


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)
