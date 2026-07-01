"""Output rendering: the JSON envelope and human-readable formatters.

The JSON envelope matches the convention pku-captain already consumes for the
``plib`` / ``pku3b`` CLIs:

* success → ``{"ok": true, "data": <payload>}``
* failure → ``{"ok": false, "error": {"code": ..., "message": ...}}``

The envelope is always written to **stdout**, even on failure, so a subprocess
caller parses one stream.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any

from .errors import DeanError
from .models import (
    FileItem,
    GuideDoc,
    NoticeDoc,
    NoticeItem,
    Page,
    RuleDoc,
    RuleItem,
    SidebarLink,
)


def jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / Page into plain JSON-friendly values."""
    if isinstance(obj, Page):
        return {
            "page": obj.page,
            "last_page": obj.last_page,
            "count": len(obj.items),
            "items": [jsonable(i) for i in obj.items],
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(i) for i in obj]
    return obj


def emit_json_ok(data: Any) -> None:
    json.dump({"ok": True, "data": jsonable(data)}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def emit_json_error(err: DeanError) -> None:
    json.dump({"ok": False, "error": err.to_dict()}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


# -- human renderers --------------------------------------------------------


def render_sidebar(links: list[SidebarLink]) -> str:
    out: list[str] = []
    current = object()
    for link in links:
        if link.category != current:
            current = link.category
            out.append(f"\n# {link.category}")
        out.append(f"  {link.title}\n    {link.url}")
    return "\n".join(out).lstrip("\n")


def render_rules(page: Page) -> str:
    header = _page_header(page, "rules")
    rows = [f"  [{it.id:>4}] {it.title}" for it in page.items]
    return "\n".join([header, *rows]) if rows else header + "\n  (no rules found)"


def render_rule_doc(doc: RuleDoc) -> str:
    return f"{doc.title}\n{'=' * len(doc.title)}\n{doc.url}\n\n{doc.text}"


def render_guide(doc: GuideDoc) -> str:
    out = [doc.title, "=" * len(doc.title), doc.url]
    if doc.update_date:
        out.append(f"更新日期：{doc.update_date}")
    for sec in doc.sections:
        out.append(f"\n## {sec.heading}")
        if sec.body:
            out.append(sec.body)
    if doc.related:
        out.append("\n## 相关链接")
        for rel in doc.related:
            out.append(f"  [{rel.group}] {rel.title}\n    {rel.url}")
    return "\n".join(out)


def render_notices(page: Page) -> str:
    header = _page_header(page, "notices")
    rows = [_notice_row(it) for it in page.items]
    return "\n".join([header, *rows]) if rows else header + "\n  (no notices found)"


def render_notice_list(items: list[NoticeItem]) -> str:
    head = f"notices — {len(items)} item(s), all pages"
    return "\n".join([head, *(_notice_row(it) for it in items)])


def render_notice_doc(doc: NoticeDoc) -> str:
    out = [doc.title, "=" * len(doc.title), doc.url]
    if doc.date:
        out.append(doc.date)
    out.append("")
    out.append(doc.text)
    return "\n".join(out)


def _notice_row(it: NoticeItem) -> str:
    suffix = f"  ({it.date})" if it.date else ""
    return f"  [{it.id:>4}] {it.title}{suffix}"


def render_files(page: Page) -> str:
    header = _page_header(page, "files")
    rows = []
    for it in page.items:
        meta = []
        if it.date:
            meta.append(it.date)
        if it.downloads is not None:
            meta.append(f"{it.downloads} downloads")
        suffix = f"  ({', '.join(meta)})" if meta else ""
        rows.append(f"  [{it.id:>4}] {it.title}{suffix}")
    return "\n".join([header, *rows]) if rows else header + "\n  (no files found)"


def render_rule_list(items: list[RuleItem]) -> str:
    rows = [f"  [{it.id:>4}] {it.title}" for it in items]
    head = f"rules — {len(items)} item(s), all pages"
    return "\n".join([head, *rows])


def render_file_list(items: list[FileItem]) -> str:
    rows = []
    for it in items:
        meta = []
        if it.date:
            meta.append(it.date)
        if it.downloads is not None:
            meta.append(f"{it.downloads} downloads")
        suffix = f"  ({', '.join(meta)})" if meta else ""
        rows.append(f"  [{it.id:>4}] {it.title}{suffix}")
    head = f"files — {len(items)} item(s), all pages"
    return "\n".join([head, *rows])


def _page_header(page: Page, label: str) -> str:
    return f"{label} — page {page.page}/{page.last_page}, {len(page.items)} item(s)"
