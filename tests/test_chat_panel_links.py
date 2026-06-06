"""Clickable link rendering in chat messages."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QFrame  # noqa: E402

from src.ui.chat_panel import (
    ChatPanel,
    MathMessageView,
    _contains_latex,
    _estimate_message_html_height,
    _mathjax_document,
    _message_html,
)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_assistant_markdown_link_renders_anchor() -> None:
    html = _message_html("查看 [官网](https://example.com/path?q=1&x=2)", "assistant")

    assert "<a href='https://example.com/path?q=1&amp;x=2'>官网</a>" in html


def test_assistant_bare_url_renders_anchor_without_trailing_punctuation() -> None:
    html = _message_html("链接：https://example.com/demo。", "assistant")

    assert "<a href='https://example.com/demo'>https://example.com/demo</a>。" in html


def test_user_message_linkifies_without_full_markdown_rendering() -> None:
    html = _message_html("我看 https://example.com\n**不要加粗**", "user")

    assert "<a href='https://example.com'>https://example.com</a>" in html
    assert "**不要加粗**" in html


def test_inline_code_and_fenced_code_do_not_linkify_urls() -> None:
    inline = _message_html("运行 `open https://example.com`", "assistant")
    fenced = _message_html("```text\nhttps://example.com\n```", "assistant")

    assert "<code" in inline
    assert "<a href" not in inline
    assert "<pre" in fenced
    assert "<a href" not in fenced


def test_inline_latex_renders_without_breaking_markdown_link() -> None:
    html = _message_html("公式 $a \\times b$ 见 [说明](https://example.com)", "assistant")

    assert "\\(a \\times b\\)" in html
    assert "math-inline" in html
    assert "<a href='https://example.com'>说明</a>" in html


def test_block_latex_renders_as_own_block() -> None:
    html = _message_html("前文\n$$\nE = mc^2\n$$\n后文", "assistant")

    assert "\\[E = mc^2\\]" in html
    assert "math-block" in html
    assert "前文" in html
    assert "后文" in html


def test_latex_inside_fenced_code_is_not_rendered() -> None:
    html = _message_html("```text\n$a \\times b$\n```", "assistant")

    assert "<pre" in html
    assert "math-inline" not in html
    assert "$a \\times b$" in html


def test_latex_detection_ignores_code_blocks() -> None:
    assert _contains_latex("公式 $x^2$") is True
    assert _contains_latex("```text\n$x^2$\n```") is False
    assert _contains_latex("代码 `\\frac{1}{2}`") is False


def test_mathjax_document_loads_mathjax_and_preserves_markdown_html() -> None:
    body = _message_html("公式 $x^2$ 和 [链接](https://example.com)", "assistant")
    document = _mathjax_document(body)

    assert "MathJax" in document
    assert "tex-chtml.js" in document
    assert "\\(x^2\\)" in document
    assert "<a href='https://example.com'>链接</a>" in document


def test_mathjax_document_avoids_internal_vertical_scrolling() -> None:
    document = _mathjax_document(_message_html("$$\na=b\n$$", "assistant"))

    assert "height: auto;" in document
    assert "min-height: 0;" in document
    assert "overflow: visible;" in document
    assert "overflow-x: auto" not in document


def test_mathjax_height_estimate_expands_multiline_formula() -> None:
    body = _message_html(
        "第一行\n$$\n\\begin{aligned}a&=b+c\\\\d&=e+f\\\\g&=h+i\\end{aligned}\n$$\n最后一行",
        "assistant",
    )

    assert _estimate_message_html_height(body) > 60


def test_message_bubbles_have_capped_widths(app: QApplication) -> None:
    # Bubbles use fixed maximum widths (the branch's viewport-responsive sizing
    # is not integrated into main's chat panel).
    panel = ChatPanel()
    panel.resize(380, 640)
    panel.show()
    panel.add_assistant_message("assistant")
    panel.add_user_message("user")
    QApplication.processEvents()

    bubbles = panel.findChildren(QFrame, "MessageBubble")
    assistant = next(b for b in bubbles if b.property("messageRole") == "assistant")
    user = next(b for b in bubbles if b.property("messageRole") == "user")

    assert assistant.maximumWidth() == 720
    assert user.maximumWidth() == 440


def test_assistant_message_uses_math_web_view(app: QApplication) -> None:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        pytest.skip("QWebEngineView aborts under Qt offscreen platform")
    panel = ChatPanel()
    panel.add_assistant_message("公式 $x^2$")
    QApplication.processEvents()

    view = panel.findChild(MathMessageView, "MessageText")
    assert view is not None
    assert "\\(x^2\\)" in view.text()


def test_math_view_can_shrink_after_mathjax_ready(app: QApplication) -> None:
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        pytest.skip("QWebEngineView aborts under Qt offscreen platform")
    view = MathMessageView()
    view.setText(_message_html("第一行\n$$\na=b\n$$\n最后一行", "assistant"))
    estimated = view.height()

    view._apply_content_height({"height": 30, "ready": False})
    assert view.height() >= estimated

    view._apply_content_height({"height": 30, "ready": True})
    assert view.height() < estimated


def test_streaming_math_uses_lightweight_body_until_final(app: QApplication) -> None:
    panel = ChatPanel()
    panel.append_assistant_delta("先算 $x")
    panel.append_assistant_delta("^2$")
    QApplication.processEvents()

    assert panel._streaming_bubble is not None
    assert not isinstance(panel._streaming_bubble, MathMessageView)
