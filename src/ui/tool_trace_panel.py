"""Visible tool-call trace panel for AgentEvent rendering."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
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
        self._rows: dict[str, QLabel] = {}

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
        label = self._make_label()
        label.setText(_trace_html(name, "调用中", arguments, None, "pending"))
        self._rows[call_id] = label
        self._trace_layout.insertWidget(self._trace_layout.count() - 1, label)
        self._scroll_to_bottom()

    def update_tool_result(self, call_id: str, name: str, result: Any) -> None:
        label = self._rows.get(call_id)
        if label is None:
            label = self._make_label()
            self._rows[call_id] = label
            self._trace_layout.insertWidget(self._trace_layout.count() - 1, label)

        success = bool(getattr(result, "success", False))
        body = getattr(result, "data", None) if success else getattr(result, "error", None)
        status = "成功" if success else "失败"
        role = "success" if success else "error"
        label.setText(_trace_html(name, status, None, _format_tool_result(name, body), role))
        self._scroll_to_bottom()

    def clear(self) -> None:
        while self._trace_layout.count() > 1:
            item = self._trace_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

    def _make_label(self) -> QLabel:
        label = QLabel()
        label.setTextFormat(label.textFormat().RichText)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return label

    def _scroll_to_bottom(self) -> None:
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())


def _trace_html(
    name: str,
    status: str,
    arguments: dict[str, Any] | None,
    result: Any,
    role: str,
) -> str:
    colors = {
        "pending": ("#fff6ed", "#8c0000"),
        "success": ("#f2f7f2", "#166534"),
        "error": ("#fef2f2", "#b42318"),
    }
    background, foreground = colors.get(role, colors["pending"])
    detail = _to_json(arguments) if arguments is not None else str(result)
    return (
        f"<div style='padding: 10px; border-radius: 8px; "
        f"background: {background}; color: {foreground};'>"
        f"<div style='font-weight: 600;'>{_escape(name)}</div>"
        f"<div style='margin: 3px 0 8px 0;'>状态：{_escape(status)}</div>"
        f"<pre style='white-space: pre-wrap; margin: 0;'>{_escape(detail)}</pre>"
        "</div>"
    )


def _format_tool_result(name: str, body: Any) -> str:
    if name == "pku3b_assignments" and isinstance(body, dict):
        return _format_assignments(body)
    if name == "pku3b_announcements" and isinstance(body, dict):
        return _format_announcements(body)
    if name == "pku3b_coursetable" and isinstance(body, dict):
        return _format_course_table(body)
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


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
