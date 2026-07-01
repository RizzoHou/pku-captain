"""Public dean.pku.edu.cn resources via the vendored ``dean`` library.

``pku-dean-cli`` is vendored under ``vendor/pku-dean-cli`` (git subtree) and
imported **in-process** as ``dean`` — no subprocess, no sibling ``.venv``. It
fetches **public** resources from PKU's Office of Educational Administration
site (no login required). The Tool shapes ``dean.resources.*`` calls into the
same ``ToolResult`` / ``{"ok": ..., "data": ...}`` envelope the agent and
dashboard already consume.

This tool exposes the **read** surface (sidebar, guide, rules, file listings)
plus the two file-download actions ``download_get`` / ``openinfo_get`` — they
fetch a file by id (or several) into a local directory (default
``downloads/dean/<kind>``, which is gitignored) and return the saved paths.
``--all`` (fetch every page) stays omitted: it walks every page over HTTP and
would flood the conversation; callers page with ``page``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from dean import resources
from dean.client import DeanClient
from dean.errors import DeanError
from dean.output import jsonable

from .base import Tool, ToolResult

DEFAULT_TIMEOUT = 60.0
# Downloads stream a binary over HTTP, so they get a longer ceiling than the
# read endpoints (mirrors plib's download timeout).
DOWNLOAD_TIMEOUT = 180.0
_REPO_ROOT = Path(__file__).resolve().parents[2]

# A client factory lets tests inject a fake DeanClient (or one wrapping a stub
# HTTP session) without touching the network; production builds a real client
# per call with the appropriate timeout.
ClientFactory = Callable[[float], DeanClient]


def _default_client_factory(timeout: float) -> DeanClient:
    return DeanClient(timeout=timeout)


def fetch_dean(
    call: Callable[[DeanClient], Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Run one ``resources.*`` call in-process and return the stable envelope.

    Returns ``{"ok": True, "data": jsonable(result)}`` on success or
    ``{"ok": False, "error": <message>}`` when the library raises
    :class:`~dean.errors.DeanError` (network/parse/not-found). Shared by
    :class:`DeanResourcesTool` and ``DeanUpdatesTool`` so both go through one
    error-isolated path with identical ``data`` shapes.
    """
    factory = client_factory or _default_client_factory
    client = factory(timeout)
    try:
        result = call(client)
    except DeanError as exc:
        return {"ok": False, "error": exc.message}
    return {"ok": True, "data": jsonable(result)}


class DeanResourcesTool(Tool):
    name: ClassVar[str] = "dean_resources"
    description: ClassVar[str] = (
        "Fetch public resources from PKU's Office of Educational Administration "
        "(教务部, dean.pku.edu.cn) — no login needed. "
        "Actions: `sidebar` (student-service links by category), `guide` by id "
        "(content behind a sidebar link), `rules_list` (校级/国家 regulations, "
        "scope school|national), `rules_show` by id (full rule text), "
        "`notice_list` (教务部通知公告), `notice_show` by id (full notice text), "
        "`download_list` (downloadable forms/handbooks), `download_get` by id(s) "
        "(save those forms/handbooks to disk), `openinfo_list` "
        "(information-disclosure files), `openinfo_get` by id(s) (save those "
        "files to disk). `guide` ids come from `sidebar` URLs, "
        "`rules_show` ids from `rules_list`, `notice_show` ids from "
        "`notice_list`, `download_get` ids from `download_list`, and "
        "`openinfo_get` ids from `openinfo_list`, so list first, then show/get. "
        "Use this for questions like “选课手册在哪下载” (then `download_get` to save "
        "it), “本科生学籍管理办法怎么规定的”, “教务部最近发了什么通知”, "
        "or “教务部最近公示了什么”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "sidebar",
                    "guide",
                    "rules_list",
                    "rules_show",
                    "notice_list",
                    "notice_show",
                    "download_list",
                    "download_get",
                    "openinfo_list",
                    "openinfo_get",
                ],
                "description": "Which dean.pku.edu.cn resource to fetch.",
            },
            "id": {
                "type": "integer",
                "description": (
                    "Resource id. Required for `guide`, `rules_show`, and "
                    "`notice_show`; accepted (alongside `ids`) by `download_get` "
                    "and `openinfo_get`."
                ),
            },
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "File ids to download for `download_get` / `openinfo_get`. "
                    "Combined with `id` if both are given."
                ),
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Directory to save downloaded files into for `download_get` "
                    "/ `openinfo_get`. Default: downloads/dean/<kind>."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["school", "national"],
                "description": (
                    "For `rules_list`: school = 北大校级 regulations, "
                    "national = 国家/上级 documents. Default school."
                ),
            },
            "page": {
                "type": "integer",
                "description": (
                    "Page number for `rules_list` / `notice_list` / "
                    "`download_list` / `openinfo_list`. Default 1. The response "
                    "carries `last_page`."
                ),
                "minimum": 1,
                "default": 1,
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self._client_factory = client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip()
        if action == "sidebar":
            return self._call(resources.get_sidebar)
        if action == "guide":
            return self._show(resources.show_guide, args, "guide")
        if action == "rules_show":
            return self._show(resources.show_rule, args, "rules show")
        if action == "rules_list":
            scope = str(args.get("scope") or "school").strip()
            page = self._page(args)
            return self._call(lambda c: resources.list_rules(c, scope, page=page))
        if action == "notice_show":
            return self._show(resources.show_notice, args, "notice show")
        if action == "notice_list":
            page = self._page(args)
            return self._call(lambda c: resources.list_notices(c, page=page))
        if action == "download_list":
            page = self._page(args)
            return self._call(lambda c: resources.list_files(c, "download", page=page))
        if action == "download_get":
            return self._download("download", args)
        if action == "openinfo_list":
            page = self._page(args)
            return self._call(lambda c: resources.list_files(c, "openinfo", page=page))
        if action == "openinfo_get":
            return self._download("openinfo", args)
        return ToolResult(success=False, error=f"unknown action: {action!r}")

    def _call(
        self, call: Callable[[DeanClient], Any], *, timeout: float | None = None
    ) -> ToolResult:
        run = fetch_dean(
            call,
            timeout=timeout if timeout is not None else self.timeout,
            client_factory=self._client_factory,
        )
        if not run["ok"]:
            return ToolResult(success=False, error=run["error"])
        return ToolResult(success=True, data=run["data"])

    def _show(
        self,
        call: Callable[[DeanClient, int], Any],
        args: dict[str, Any],
        label: str,
    ) -> ToolResult:
        resource_id = args.get("id")
        if not isinstance(resource_id, int):
            return ToolResult(success=False, error=f"`{label}` requires integer `id`")
        return self._call(lambda c: call(c, resource_id))

    def _download(self, kind: str, args: dict[str, Any]) -> ToolResult:
        ids = [item for item in args.get("ids") or [] if isinstance(item, int)]
        if isinstance(args.get("id"), int):
            ids.insert(0, args["id"])
        if not ids:
            return ToolResult(success=False, error=f"`{kind}_get` requires `id` or `ids`")
        output_dir = str(
            args.get("output_dir") or (_REPO_ROOT / "downloads" / "dean" / kind)
        )
        factory = self._client_factory or _default_client_factory
        client = factory(DOWNLOAD_TIMEOUT)
        try:
            saved = [
                str(resources.download_file(client, kind, fid, output_dir)) for fid in ids
            ]
        except DeanError as exc:
            return ToolResult(success=False, error=exc.message)
        return ToolResult(success=True, data={"saved": saved, "count": len(saved)})

    @staticmethod
    def _page(args: dict[str, Any]) -> int:
        page = args.get("page")
        if isinstance(page, int) and page > 0:
            return page
        return 1
