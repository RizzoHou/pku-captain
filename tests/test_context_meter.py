"""ContextMeter widget: the chat-header bar that visualizes context occupation.

Runs headless via Qt's offscreen platform.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.ui.chat_panel import ChatPanel, ContextMeter, _fmt_tokens  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_fmt_tokens() -> None:
    assert _fmt_tokens(0) == "0"
    assert _fmt_tokens(950) == "950"
    assert _fmt_tokens(12_300) == "12.3K"
    assert _fmt_tokens(1_000_000) == "1.0M"


def test_meter_renders_absolute_figure(app: QApplication) -> None:
    meter = ContextMeter()
    meter.set_usage(12_300, 1_000_000)
    label = meter._label.text()
    assert "12.3K" in label and "1.0M" in label and "1.2%" in label
    assert "约" not in label  # real usage is not marked approximate
    assert meter._bar.value() == 12  # 1.23% -> 12 permille


def test_meter_marks_estimate(app: QApplication) -> None:
    meter = ContextMeter()
    meter.set_usage(5_000, 1_000_000, estimated=True)
    assert meter._label.text().startswith("上下文 约 ")


def test_meter_level_escalates(app: QApplication) -> None:
    meter = ContextMeter()
    meter.set_usage(10_000, 1_000_000)  # 1%
    assert meter._bar.property("level") == "ok"
    meter.set_usage(800_000, 1_000_000)  # 80%
    assert meter._bar.property("level") == "warn"
    meter.set_usage(950_000, 1_000_000)  # 95%
    assert meter._bar.property("level") == "full"


def test_meter_clamps_overflow(app: QApplication) -> None:
    meter = ContextMeter()
    meter.set_usage(2_000_000, 1_000_000)  # over capacity
    assert meter._bar.value() == 1000  # capped at 100%


def test_meter_handles_unknown_window(app: QApplication) -> None:
    meter = ContextMeter()
    meter.set_usage(100, 0)
    assert meter._label.text() == "上下文 —"
    assert meter._bar.value() == 0


def test_chat_panel_delegates_to_meter(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_context_usage(20_000, 1_000_000)
    assert "20.0K" in panel._context_meter._label.text()
