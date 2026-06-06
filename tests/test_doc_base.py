"""Doc base tools — lexical search ranking + vision read plumbing.

`doc_read` shells to pdftoppm and calls a vision API; both are stubbed here
(rendering monkeypatched, a fake in-process vision provider) so the test is
deterministic and needs neither poppler nor a network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm.base import ChatResponse, LLMProvider
from src.tools import doc_base
from src.tools.doc_base import (
    DocBaseReader,
    DocBaseReadTool,
    DocBaseSearchTool,
    _parse_pages,
    load_manifest,
)

_DOCS = [
    {
        "source": "a.pdf",
        "volume": "本科培养方案2025-理科卷",
        "breadcrumb": ["理学部", "北京大学数学科学学院"],
        "title": "数学与应用数学专业（基础数学方向）",
        "path": "本科培养方案2025-理科卷/理学部/北京大学数学科学学院/基础数学.pdf",
        "page_start": 46,
        "page_end": 51,
        "pages": 6,
        "kind": "section",
    },
    {
        "source": "a.pdf",
        "volume": "本科培养方案2025-理科卷",
        "breadcrumb": ["理学部", "北京大学物理学院"],
        "title": "物理学专业",
        "path": "本科培养方案2025-理科卷/理学部/北京大学物理学院/物理学.pdf",
        "page_start": 60,
        "page_end": 65,
        "pages": 6,
        "kind": "section",
    },
    {
        "source": "b.pdf",
        "volume": "本科辅修双专业培养方案2025",
        "breadcrumb": ["理学部"],
        "title": "数学科学学院",
        "path": "本科辅修双专业培养方案2025/理学部/数学科学学院.pdf",
        "page_start": 13,
        "page_end": 16,
        "pages": 4,
        "kind": "section",
    },
]


@pytest.fixture
def doc_dir(tmp_path: Path) -> Path:
    base = tmp_path / "doc_base"
    base.mkdir()
    (base / "manifest.json").write_text(
        json.dumps({"note": "test", "documents": _DOCS}, ensure_ascii=False),
        encoding="utf-8",
    )
    for doc in _DOCS:
        pdf = base / doc["path"]
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4 stub")
    return base


class _FakeVision(LLMProvider):
    name = "fake-vision"

    def __init__(self) -> None:
        self.last_messages: list = []

    def chat(self, messages, tools=None) -> ChatResponse:
        self.last_messages = messages
        return ChatResponse(text="毕业总学分：138")


# --- manifest + search ---------------------------------------------------


def test_load_manifest(doc_dir: Path) -> None:
    entries = load_manifest(doc_dir)
    assert len(entries) == 3
    assert entries[0].breadcrumb == ("理学部", "北京大学数学科学学院")


def test_search_ranks_title_match_first(doc_dir: Path) -> None:
    tool = DocBaseSearchTool(doc_base_dir=doc_dir)
    result = tool.invoke({"query": "数学与应用数学"})
    assert result.success
    assert result.data[0]["title"] == "数学与应用数学专业（基础数学方向）"
    assert result.data[0]["abs_path"].endswith("基础数学.pdf")


def test_search_unsegmented_cjk_query(doc_dir: Path) -> None:
    # No spaces: bigram overlap must still surface the math docs over physics.
    tool = DocBaseSearchTool(doc_base_dir=doc_dir)
    result = tool.invoke({"query": "数学科学学院"})
    assert result.success
    titles = [hit["title"] for hit in result.data]
    assert "物理学专业" not in titles[:1]


def test_search_empty_query_browses_all(doc_dir: Path) -> None:
    tool = DocBaseSearchTool(doc_base_dir=doc_dir)
    result = tool.invoke({"query": ""})
    assert result.success
    assert len(result.data) == 3
    # browse mode is unscored, in document (path) order
    assert "score" not in result.data[0]


def test_search_volume_filter(doc_dir: Path) -> None:
    tool = DocBaseSearchTool(doc_base_dir=doc_dir)
    result = tool.invoke({"query": "", "volume": "辅修"})
    assert result.success
    assert len(result.data) == 1
    assert result.data[0]["title"] == "数学科学学院"


def test_real_manifest_loads() -> None:
    # The committed corpus loads and is non-trivial.
    entries = load_manifest()
    assert len(entries) > 100


# --- page spec -----------------------------------------------------------


def test_parse_pages() -> None:
    assert _parse_pages("", 6) == [1, 2, 3, 4, 5, 6]
    assert _parse_pages("all", 6) == [1, 2, 3, 4, 5, 6]
    assert _parse_pages("2-4", 6) == [2, 3, 4]
    assert _parse_pages("3", 6) == [3]
    assert _parse_pages("4-99", 6) == [4, 5, 6]  # clamped to total


def test_parse_pages_invalid() -> None:
    with pytest.raises(ValueError):
        _parse_pages("5-2", 6)


# --- read tool (image injection) -----------------------------------------


def test_read_tool_returns_images_without_a_vision_call(
    doc_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tool renders pages and hands them back via ToolResult.images for the
    # agent to inject; it never calls a vision model itself.
    monkeypatch.setattr(
        doc_base,
        "_render_pages",
        lambda pdf, pages, dpi: [f"data:image/png;base64,page{p}" for p in pages],
    )
    tool = DocBaseReadTool(doc_base_dir=doc_dir)
    result = tool.invoke({"path": _DOCS[0]["path"], "pages": "1-2"})
    assert result.success
    assert result.images == (
        "data:image/png;base64,page1",
        "data:image/png;base64,page2",
    )
    assert result.data["pages_read"] == [1, 2]
    assert result.data["truncated"] is False
    assert "数学" in result.data["note"]


def test_read_tool_unknown_path_errors(doc_dir: Path) -> None:
    tool = DocBaseReadTool(doc_base_dir=doc_dir)
    result = tool.invoke({"path": "本科培养方案2025-理科卷/不存在.pdf"})
    assert not result.success
    assert not result.images
    assert "文档库" in (result.error or "")


def test_read_tool_truncates_long_request(
    doc_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        doc_base,
        "_render_pages",
        lambda pdf, pages, dpi: ["data:image/png;base64,x" for _ in pages],
    )
    tool = DocBaseReadTool(doc_base_dir=doc_dir, max_pages=1)
    result = tool.invoke({"path": _DOCS[0]["path"], "pages": "1-6"})
    assert result.success
    assert result.data["truncated"] is True
    assert len(result.images) == 1
    assert len(result.data["pages_read"]) == 1
    assert "仅渲染前" in result.data["note"]


# --- reader service (encapsulated Q&A, dashboard) ------------------------


def test_reader_builds_multimodal_message_and_answers(
    doc_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        doc_base,
        "_render_pages",
        lambda pdf, pages, dpi: [f"data:image/png;base64,page{p}" for p in pages],
    )
    vision = _FakeVision()
    reader = DocBaseReader(vision, doc_base_dir=doc_dir)
    result = reader.read(_DOCS[0]["path"], question="毕业总学分？", pages="1-2")
    assert result.success
    assert result.data["answer"] == "毕业总学分：138"
    assert result.data["pages_read"] == [1, 2]
    # the vision provider got one multimodal user message: 2 images + 1 text
    content = vision.last_messages[0].content
    assert [part["type"] for part in content] == ["image_url", "image_url", "text"]
    assert "毕业总学分？" in content[-1]["text"]


def test_reader_unknown_path_errors(doc_dir: Path) -> None:
    reader = DocBaseReader(_FakeVision(), doc_base_dir=doc_dir)
    result = reader.read("本科培养方案2025-理科卷/不存在.pdf")
    assert not result.success
    assert "文档库" in (result.error or "")
