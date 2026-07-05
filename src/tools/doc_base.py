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
   and returns them (via `ToolResult.images`) for the agent to inject into the
   conversation, so a vision-capable chat brain (Kimi K2.6) reads the pages
   *itself* — no text middleman. It registers only while the active brain is
   Kimi (a text brain can't read the injected images).

`doc_search` registers in every mode. `DocBaseReader` is the encapsulated
counterpart used by the dashboard's one-off "让 Captain 阅读" dialog: it renders,
asks the vision model directly, and returns a self-contained text answer — the
right shape when there is no chat to inject images into.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..llm.base import ChatMessage, LLMProvider, image_part, text_part
from .base import Tool, ToolResult

# PDF rendering runs fully in-process via pypdfium2 (bundled PDFium, no external
# binary) plus Pillow for PNG encoding — both are pip wheels, so the packaged app
# needs no poppler/pdftoppm on the user's machine. Imported defensively so the
# module still loads (and doc_search still works) on a platform without a wheel;
# doc_read then raises an actionable DocReadError instead of failing at import.
try:
    import pypdfium2 as _pdfium
except Exception:  # pragma: no cover - platform without a pypdfium2 wheel
    _pdfium = None

try:
    from PIL import Image as _PILImage
except Exception:  # pragma: no cover - Pillow missing
    _PILImage = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_BASE_DIR = _REPO_ROOT / "doc_base"
_MANIFEST_NAME = "manifest.json"

DEFAULT_TOP_K = 10
MAX_TOP_K = 50

# A 150-DPI page costs Kimi roughly ~2.5k prompt tokens (verified live), so the
# page cap is what keeps a read inside the model's window. 24 pages ≈ 60k tokens,
# comfortable in Kimi K2.6's 256k window; longer documents are read in slices via
# the `pages` argument.
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


class DocReadError(ValueError):
    """A user-actionable failure while resolving/rendering a doc-base document."""


def _render_doc(
    by_path: dict[str, DocEntry],
    doc_base_dir: Path,
    args: dict[str, Any],
    dpi: int,
    max_pages: int,
) -> tuple[DocEntry, list[int], int, bool, list[str]]:
    """Resolve `args['path']`/`args['pages']` and render the pages to data URIs.

    Shared by `DocBaseReadTool` (agent image injection) and `DocBaseReader`
    (dashboard standalone Q&A). Raises `DocReadError` with a Chinese message on
    any user-actionable failure (bad path, missing file, bad page spec, missing
    render deps). Returns `(entry, page_nums, total_pages, truncated, images)`.
    """
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        raise DocReadError("path 不能为空")
    entry = by_path.get(rel_path)
    if entry is None:
        raise DocReadError(f"文档不在文档库中：{rel_path}")
    pdf_path = entry.abs_path(doc_base_dir)
    if not pdf_path.exists():
        raise DocReadError(f"文档文件缺失：{rel_path}")

    total = entry.pages or _pdf_page_count(pdf_path)
    try:
        requested = _parse_pages(str(args.get("pages") or ""), total)
    except ValueError as exc:
        raise DocReadError(str(exc)) from exc
    truncated = len(requested) > max_pages
    page_nums = requested[:max_pages]
    if not page_nums:
        raise DocReadError("没有可读取的页面")

    try:
        images = _render_pages(pdf_path, page_nums, dpi)
    except DocReadError:
        raise
    except Exception as exc:  # pypdfium2 / Pillow rendering failure
        raise DocReadError(f"渲染 PDF 失败：{exc}") from exc
    return entry, page_nums, total, truncated, images


class DocBaseReadTool(Tool):
    name: ClassVar[str] = "doc_read"
    description: ClassVar[str] = (
        "Read a PKU curriculum document yourself. Renders the document's pages "
        "to images and adds them to the conversation for you to read directly — "
        "you are a vision-capable model, so read the course tables and "
        "flowcharts from the images and answer from them, never guessing credit "
        "numbers or course lists. Pass the `path` returned by doc_search, and "
        "`pages` (e.g. '1-6') to read a slice of a long document. After calling "
        "this, the page images appear as the next message; answer from them."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Document `path` from doc_search (relative to doc_base/).",
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
        doc_base_dir: Path = _DOC_BASE_DIR,
        dpi: int = READ_DPI,
        max_pages: int = MAX_READ_PAGES,
    ) -> None:
        self._doc_base_dir = doc_base_dir
        self._dpi = dpi
        self._max_pages = max_pages
        self._by_path = {e.rel_path: e for e in load_manifest(doc_base_dir)}

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        try:
            entry, page_nums, total, truncated, images = _render_doc(
                self._by_path, self._doc_base_dir, args, self._dpi, self._max_pages
            )
        except DocReadError as exc:
            return ToolResult(success=False, error=str(exc))

        note = f"《{entry.title}》（{entry.volume}）第 {page_nums[0]}–{page_nums[-1]} 页"
        if truncated:
            note += f"（仅渲染前 {len(page_nums)} 页 / 共 {total} 页，用 pages 读取其余）"
        return ToolResult(
            success=True,
            data={
                "path": entry.rel_path,
                "title": entry.title,
                "volume": entry.volume,
                "pages_read": page_nums,
                "total_pages": total,
                "truncated": truncated,
                "note": note,
            },
            images=tuple(images),
        )


class DocBaseReader:
    """Encapsulated vision Q&A over one doc-base document (returns text).

    The standalone counterpart to the agent's image-injecting `doc_read` tool,
    used by the dashboard's 让 Captain 阅读 dialog: it renders the pages, asks the
    vision model (Kimi) directly, and returns a self-contained answer — the
    right shape for a one-off read with no chat to feed images into. It is a
    plain service, not a `Tool`, so it never enters the agent registry.
    """

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

    def read(
        self,
        path: str,
        question: str | None = None,
        pages: str | None = None,
    ) -> ToolResult:
        args = {"path": path, "pages": pages or ""}
        try:
            entry, page_nums, total, truncated, images = _render_doc(
                self._by_path, self._doc_base_dir, args, self._dpi, self._max_pages
            )
        except DocReadError as exc:
            return ToolResult(success=False, error=str(exc))

        instruction = (question or "").strip() or (
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
        except Exception as exc:  # surface vision-API failures to the dialog
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
                "path": entry.rel_path,
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
    """Best-effort page count via pypdfium2; 0 if unavailable."""
    if _pdfium is None:
        return 0
    try:
        pdf = _pdfium.PdfDocument(str(pdf_path))
    except Exception:
        return 0
    try:
        return len(pdf)
    finally:
        pdf.close()


def _render_pages(pdf_path: Path, page_nums: list[int], dpi: int) -> list[str]:
    """Render the given 1-based pages to PNG data URIs via pypdfium2 + Pillow."""
    if _pdfium is None or _PILImage is None:
        raise DocReadError(
            "缺少 PDF 渲染依赖 pypdfium2 / Pillow；请运行 pip install pypdfium2 Pillow。"
        )
    scale = dpi / 72.0  # pypdfium2 renders at 72 DPI * scale
    uris: list[str] = []
    pdf = _pdfium.PdfDocument(str(pdf_path))
    try:
        total = len(pdf)
        for page in page_nums:  # 1-based
            index = page - 1
            if index < 0 or index >= total:
                continue
            image = pdf[index].render(scale=scale).to_pil().convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
            uris.append("data:image/png;base64," + base64.b64encode(data).decode())
    finally:
        pdf.close()
    return uris
