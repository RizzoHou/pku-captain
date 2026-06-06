"""ChatPanel model switcher — populate, visibility gating, emit/no-emit."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.ui.chat_panel import ChatPanel  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


_MODELS = [("deepseek", "DeepSeek V4 Pro"), ("kimi", "Kimi K2.6")]


def test_two_models_shows_switcher_with_current_selected(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_models(_MODELS, "kimi")
    combo = panel._model_combo
    assert combo.isVisibleTo(panel)
    assert combo.count() == 2
    assert combo.itemData(combo.currentIndex()) == "kimi"


def test_single_or_no_model_hides_switcher(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_models([("deepseek", "DeepSeek V4 Pro")], "deepseek")
    assert not panel._model_combo.isVisibleTo(panel)
    panel.set_models([], None)
    assert not panel._model_combo.isVisibleTo(panel)


def test_user_selection_emits_key(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_models(_MODELS, "deepseek")
    seen: list[str] = []
    panel.model_change_requested.connect(seen.append)
    # _emit_model_change is the `activated` slot (user picked a row).
    kimi_index = panel._model_combo.findData("kimi")
    panel._emit_model_change(kimi_index)
    assert seen == ["kimi"]


def test_set_active_model_does_not_emit(app: QApplication) -> None:
    panel = ChatPanel()
    panel.set_models(_MODELS, "deepseek")
    seen: list[str] = []
    panel.model_change_requested.connect(seen.append)
    panel.set_active_model("kimi")
    assert seen == []  # programmatic select stays silent
    assert panel._model_combo.itemData(panel._model_combo.currentIndex()) == "kimi"
