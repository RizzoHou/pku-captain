"""Doc base tools — lexical find + vision read over the split-PDF corpus.

These replace the embedding `KnowledgeSearchTool`. The doc base (`doc_base/`)
is a hierarchy of small, topic-scoped PDFs split from the PKU curriculum
documents (培养方案 / 选课手册 / 辅修双专业), indexed by `doc_base/manifest.json`.

The source PDFs are dense with tables, course-map flowcharts, and other layout
an embedding model mangles, so retrieval here is two-stage instead of semantic:

1. `DocBaseSearchTool` (`doc_search`) finds the right *document* by matching the
   query against its title / breadcrumb / volume — a pure read of the committed
   manifest, so it works offline with no index to build.
2. `DocBaseReadTool` (`doc_read`) renders the chosen document's pages to images
   and has a vision LLM (Kimi) read them and answer a question. Only the model's
   distilled answer — not the whole document — enters the agent's context, which
   is what keeps the context cost acceptable.

`doc_search` registers in every mode; `doc_read` is online-only (it shells to
`pdftoppm` and calls a vision API), and is registered only when a vision
provider is available.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..llm.base import ChatMessage, LLMProvider
from ..llm.kimi import image_part, text_part
from .base import Tool, ToolResult

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_BASE_DIR = _REPO_ROOT / "doc_base"
_MANIFEST_NAME = "manifest.json"

DEFAULT_TOP_K = 10
MAX_TOP_K = 50

# A vision page costs Kimi a roughly fixed ~1k tokens regardless of DPI, so the
# render DPI is chosen for legibility, and the page cap is what keeps a read
# inside the model's window. 24 pages fits the 32k vision model with headroom;
# longer documents are read in slices via the `pages` argument.
READ_DPI = 150
MAX_READ_PAGES = 24


@dataclass(frozen=True)
class DocEntry:
    """One split PDF, mirroring a `manifest.json` document record."""

    source: str
    volume: str
    breadcrumb: tuple[str, ...]
    title: str
    rel_path: str
    page_start: int
    page_end: int
    pages: int
    kind: str

    def abs_path(self, doc_base_dir: Path) -> Path:
        return doc_base_dir / self.rel_path

    def as_dict(self, doc_base_dir: Path) -> dict[str, Any]:
        return {
            "volume": self.volume,
            "breadcrumb": list(self.breadcrumb),
            "title": self.title,
            "path": self.rel_path,
            "abs_path": str(self.abs_path(doc_base_dir)),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "pages": self.pages,
            "kind": self.kind,
        }


def load_manifest(doc_base_dir: Path = _DOC_BASE_DIR) -> list[DocEntry]:
    """Read `manifest.json` into `DocEntry` records (empty if missing)."""
    manifest = doc_base_dir / _MANIFEST_NAME
    if not manifest.exists():
        return []
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    documents = payload.get("documents", []) if isinstance(payload, dict) else []
    entries: list[DocEntry] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        entries.append(
            DocEntry(
                source=str(doc.get("source", "")),
                volume=str(doc.get("volume", "")),
                breadcrumb=tuple(str(part) for part in doc.get("breadcrumb", [])),
                title=str(doc.get("title", "")),
                rel_path=str(doc.get("path", "")),
                page_start=int(doc.get("page_start", 0)),
                page_end=int(doc.get("page_end", 0)),
                pages=int(doc.get("pages", 0)),
                kind=str(doc.get("kind", "section")),
            )
        )
    return entries


def _score(query: str, entry: DocEntry) -> float:
    """Rank an entry against a query over title / breadcrumb / volume.

    Title matches outweigh breadcrumb, which outweigh volume. Whitespace tokens
    are matched as substrings, and — since CJK queries usually arrive unsegmented
    (e.g. ``数学学院培养方案``) — character bigram overlap is added so a query
    needs no spaces to rank the right document.
    """
    q = query.strip().lower()
    if not q:
        return 0.0
    title = entry.title.lower()
    crumb = "/".join(entry.breadcrumb).lower()
    volume = entry.volume.lower()
    fields = ((title, 3.0), (crumb, 2.0), (volume, 1.0))

    score = 0.0
    for hay, weight in fields:
        if q in hay:  # whole-query substring is the strongest signal
            score += weight * 2.0
    for token in q.split():
        for hay, weight in fields:
            if token and token in hay:
                score += weight
    bigrams = {q[i : i + 2] for i in range(len(q) - 1) if not q[i : i + 2].isspace()}
    if bigrams:
        combined = f"{title} {crumb} {volume}"
        hits = sum(1 for gram in bigrams if gram in combined)
        score += (hits / len(bigrams)) * 2.0
    return score


class DocBaseSearchTool(Tool):
    name: ClassVar[str] = "doc_search"
    description: ClassVar[str] = (
        "Find relevant PKU curriculum documents (本科培养方案 / 选课手册 / "
        "辅修双专业培养方案) by keyword. Matches the query against each "
        "document's title and 学部/院系/专业 breadcrumb (not full text), ranked "
        "by relevance, and returns the document's volume, breadcrumb, title, "
        "path, and page count. Use this to locate the right document, then call "
        "doc_read with its `path` to read the actual content."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Keywords — a 学院 / 专业 / 文档名, e.g. '数学科学学院' or "
                    "'通识教育'. Pass an empty string to list the whole doc base."
                ),
            },
            "volume": {
                "type": "string",
                "description": (
                    "Optional volume filter, e.g. '本科培养方案2025-理科卷'."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": (
                    f"Max documents to return (default {DEFAULT_TOP_K}, "
                    f"capped at {MAX_TOP_K})."
                ),
                "minimum": 1,
                "maximum": MAX_TOP_K,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, doc_base_dir: Path = _DOC_BASE_DIR) -> None:
        self._doc_base_dir = doc_base_dir
        self._entries = load_manifest(doc_base_dir)

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        volume = str(args.get("volume") or "").strip()
        top_k = args.get("top_k", DEFAULT_TOP_K)
        try:
            top_k = max(1, min(int(top_k), MAX_TOP_K))
        except (TypeError, ValueError):
            return ToolResult(success=False, error=f"top_k 必须是整数：{top_k!r}")

        entries = self._entries
        if volume:
            entries = [e for e in entries if volume.lower() in e.volume.lower()]

        if not query:
            # Browse mode: the whole (filtered) corpus in document order.
            ordered = sorted(entries, key=lambda e: e.rel_path)
            data = [e.as_dict(self._doc_base_dir) for e in ordered]
            return ToolResult(success=True, data=data)

        scored = [(_score(query, e), e) for e in entries]
        ranked = sorted(
            (pair for pair in scored if pair[0] > 0),
            key=lambda pair: (-pair[0], pair[1].rel_path),
        )[:top_k]
        data = [
            {**entry.as_dict(self._doc_base_dir), "score": round(score, 3)}
            for score, entry in ranked
        ]
        return ToolResult(success=True, data=data)


def _parse_pages(spec: str, total: int) -> list[int]:
    """Parse a 1-based page spec ('1-6', '3', 'all') into page numbers.

    Out-of-range pages are clamped to ``1..total``; an unparseable spec raises
    ``ValueError`` so the caller can surface it.
    """
    spec = spec.strip().lower()
    if not spec or spec == "all":
        return list(range(1, total + 1))
    if "-" in spec:
        lo_s, hi_s = spec.split("-", 1)
        lo, hi = int(lo_s), int(hi_s)
    else:
        lo = hi = int(spec)
    lo = max(1, lo)
    hi = min(total, hi)
    if hi < lo:
        raise ValueError(f"页码范围无效：{spec}")
    return list(range(lo, hi + 1))


class DocBaseReadTool(Tool):
    name: ClassVar[str] = "doc_read"
    description: ClassVar[str] = (
        "Read a document from the doc base and answer a question about it, using "
        "a vision model that can parse its course tables and flowcharts (which "
        "plain text extraction garbles). Pass the `path` returned by doc_search. "
        "Give a `question` to focus the read, and `pages` (e.g. '1-6') to read a "
        "slice of a long document. Returns the model's answer text."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Document `path` from doc_search (relative to doc_base/).",
            },
            "question": {
                "type": "string",
                "description": (
                    "What to read for, e.g. '毕业总学分要求是多少？'. Omit to get a "
                    "structured summary of the document."
                ),
            },
            "pages": {
                "type": "string",
                "description": (
                    "Optional 1-based page range, e.g. '1-6' or '3'. Defaults to "
                    f"the first {MAX_READ_PAGES} pages; use this to read more of a "
                    "long document."
                ),
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        vision_llm: LLMProvider,
        doc_base_dir: Path = _DOC_BASE_DIR,
        dpi: int = READ_DPI,
        max_pages: int = MAX_READ_PAGES,
    ) -> None:
        self._vision = vision_llm
        self._doc_base_dir = doc_base_dir
        self._dpi = dpi
        self._max_pages = max_pages
        self._by_path = {e.rel_path: e for e in load_manifest(doc_base_dir)}

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        rel_path = str(args.get("path") or "").strip()
        if not rel_path:
            return ToolResult(success=False, error="path 不能为空")
        entry = self._by_path.get(rel_path)
        if entry is None:
            return ToolResult(success=False, error=f"文档不在文档库中：{rel_path}")
        pdf_path = entry.abs_path(self._doc_base_dir)
        if not pdf_path.exists():
            return ToolResult(success=False, error=f"文档文件缺失：{rel_path}")

        total = entry.pages or _pdf_page_count(pdf_path)
        try:
            requested = _parse_pages(str(args.get("pages") or ""), total)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))
        truncated = len(requested) > self._max_pages
        page_nums = requested[: self._max_pages]
        if not page_nums:
            return ToolResult(success=False, error="没有可读取的页面")

        try:
            images = _render_pages(pdf_path, page_nums, self._dpi)
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="未找到 pdftoppm；请安装 poppler（brew install poppler）。",
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            return ToolResult(success=False, error=f"渲染 PDF 失败：{exc}")

        question = str(args.get("question") or "").strip()
        instruction = question or (
            "请阅读这份北京大学培养方案文档，提取并用简洁中文结构化其关键信息"
            "（专业、毕业总学分、各类课程学分要求、核心课程等）。"
        )
        prompt = (
            f"以下是文档《{entry.title}》（{entry.volume}）的第 "
            f"{page_nums[0]}–{page_nums[-1]} 页图片。只依据图片内容回答，"
            f"不要编造表格里没有的数字。\n\n{instruction}"
        )
        parts: list[dict[str, Any]] = [image_part(uri) for uri in images]
        parts.append(text_part(prompt))
        message = ChatMessage(role="user", content=parts)  # type: ignore[arg-type]

        try:
            response = self._vision.chat([message])
        except Exception as exc:  # surface vision-API failures to the agent
            return ToolResult(success=False, error=f"视觉模型读取失败：{exc}")

        note = ""
        if truncated:
            note = (
                f"（仅读取了前 {len(page_nums)} 页，共 {total} 页；"
                "用 pages 参数读取其余页面。）"
            )
        return ToolResult(
            success=True,
            data={
                "path": rel_path,
                "title": entry.title,
                "volume": entry.volume,
                "pages_read": page_nums,
                "total_pages": total,
                "truncated": truncated,
                "answer": response.text,
                "note": note,
            },
        )


def _pdf_page_count(pdf_path: Path) -> int:
    """Best-effort page count via pdfinfo; 0 if unavailable."""
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo is None:
        return 0
    out = subprocess.run(
        [pdfinfo, str(pdf_path)], capture_output=True, text=True, check=False
    )
    for line in out.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def _render_pages(pdf_path: Path, page_nums: list[int], dpi: int) -> list[str]:
    """Render the given 1-based pages to PNG data URIs via pdftoppm."""
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise FileNotFoundError("pdftoppm")
    uris: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for page in page_nums:
            prefix = tmp_dir / f"p{page}"
            subprocess.run(
                [
                    pdftoppm, "-png", "-r", str(dpi),
                    "-f", str(page), "-l", str(page),
                    str(pdf_path), str(prefix),
                ],
                capture_output=True,
                check=True,
            )
            rendered = sorted(tmp_dir.glob(f"p{page}*.png"))
            if not rendered:
                continue
            data = rendered[0].read_bytes()
            uris.append("data:image/png;base64," + base64.b64encode(data).decode())
    return uris
