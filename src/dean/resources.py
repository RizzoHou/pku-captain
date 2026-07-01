"""High-level resource API over :class:`~dean.client.DeanClient`.

These functions are the single source of truth shared by the CLI and any
library consumer (e.g. pku-captain importing the package directly). They return
the dataclasses in :mod:`dean.models`.
"""

from __future__ import annotations

from pathlib import Path

from .client import BASE_URL, INDEX_URL, WEB_URL, DeanClient
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
from .parsers import (
    parse_files,
    parse_guide,
    parse_notice_doc,
    parse_notices,
    parse_rule_doc,
    parse_rules,
    parse_sidebar,
)

# scope -> listing page
_RULES_PAGES = {
    "national": f"{WEB_URL}rules.php",
    "school": f"{WEB_URL}rules_school.php",
}
# kind -> (listing page, download type)
_FILE_PAGES = {
    "download": (f"{WEB_URL}download.php", "down"),
    "openinfo": (f"{WEB_URL}openinfo.php", "msg"),
}

MAX_PAGES = 200  # safety bound for --all


# -- sidebar ----------------------------------------------------------------


def get_sidebar(client: DeanClient) -> list[SidebarLink]:
    return parse_sidebar(client.get_html(INDEX_URL))


# -- student guide ----------------------------------------------------------


def show_guide(client: DeanClient, guide_id: int) -> GuideDoc:
    url = f"{WEB_URL}student_info.php?id={guide_id}"
    return parse_guide(client.get_html(url), guide_id, url)


# -- rules ------------------------------------------------------------------


def list_rules(client: DeanClient, scope: str, *, page: int = 1) -> Page:
    url = _rules_url(scope)
    html = client.get_html(url, params={"page": page} if page > 1 else None)
    return parse_rules(html, scope)


def list_all_rules(client: DeanClient, scope: str) -> list[RuleItem]:
    return _collect_all(lambda p: list_rules(client, scope, page=p))


def show_rule(client: DeanClient, rule_id: int) -> RuleDoc:
    url = f"{WEB_URL}rules_info.php?id={rule_id}"
    return parse_rule_doc(client.get_html(url), rule_id, url)


# -- notices ----------------------------------------------------------------


def list_notices(client: DeanClient, *, page: int = 1) -> Page:
    url = f"{WEB_URL}notice.php"
    html = client.get_html(url, params={"page": page} if page > 1 else None)
    return parse_notices(html)


def list_all_notices(client: DeanClient) -> list[NoticeItem]:
    return _collect_all(lambda p: list_notices(client, page=p))


def show_notice(client: DeanClient, notice_id: int) -> NoticeDoc:
    url = f"{WEB_URL}notice_details.php?id={notice_id}"
    return parse_notice_doc(client.get_html(url), notice_id, url)


# -- files (download / openinfo) -------------------------------------------


def list_files(client: DeanClient, kind: str, *, page: int = 1) -> Page:
    url, _ = _file_cfg(kind)
    html = client.get_html(url, params={"page": page} if page > 1 else None)
    return parse_files(html, kind)


def list_all_files(client: DeanClient, kind: str) -> list[FileItem]:
    return _collect_all(lambda p: list_files(client, kind, page=p))


def download_file(
    client: DeanClient, kind: str, file_id: int, out_dir: str | Path
) -> Path:
    _, dtype = _file_cfg(kind)
    url = f"{WEB_URL}download_down.php"
    return client.download(url, params={"type": dtype, "id": file_id}, out_dir=out_dir)


# -- internals --------------------------------------------------------------


def _rules_url(scope: str) -> str:
    try:
        return _RULES_PAGES[scope]
    except KeyError:
        raise DeanError(
            f"unknown rules scope {scope!r}; expected one of {sorted(_RULES_PAGES)}",
            code="bad_argument",
        ) from None


def _file_cfg(kind: str) -> tuple[str, str]:
    try:
        return _FILE_PAGES[kind]
    except KeyError:
        raise DeanError(
            f"unknown file kind {kind!r}; expected one of {sorted(_FILE_PAGES)}",
            code="bad_argument",
        ) from None


def _collect_all(fetch):
    """Page through a listing until the last page, stopping early if a page is empty."""
    first = fetch(1)
    items = list(first.items)
    last = min(first.last_page, MAX_PAGES)
    for p in range(2, last + 1):
        page = fetch(p)
        if not page.items:
            break
        items.extend(page.items)
    return items


__all__ = [
    "BASE_URL",
    "get_sidebar",
    "show_guide",
    "list_rules",
    "list_all_rules",
    "show_rule",
    "list_notices",
    "list_all_notices",
    "show_notice",
    "list_files",
    "list_all_files",
    "download_file",
]
