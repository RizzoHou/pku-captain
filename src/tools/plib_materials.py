"""P-Lib course-material search via the vendored ``plib_cli`` library.

``plib-cli`` is vendored under ``vendor/plib-cli`` (git subtree) and imported
**in-process** as ``plib_cli`` — no subprocess, no sibling ``.venv``. P-Lib
(pkuhub.cn) has no public JSON API, so the library scrapes HTML; this Tool
drives its :class:`~plib_cli.client.PlibClient` and shapes the dataclass results
into the same ``ToolResult`` / ``{"ok": ..., "data": ...}`` envelope the agent
and dashboard already consume.

Stored ``secrets/plib/{email,password}`` are injected as explicit
:class:`~plib_cli.config.Credentials` on every call so search / quota / download
self-authenticate (the client's login is lazy and self-healing). The credential
values are redacted from any error string before it can reach a ``ToolResult``
(and thus the LLM context / session store).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from plib_cli.client import PlibClient
from plib_cli.config import Credentials
from plib_cli.errors import PlibError

from .base import Tool, ToolResult
from .redact import redact

DEFAULT_TIMEOUT = 60.0
# Downloads stream a file over HTTP, so they get a longer ceiling than searches.
DOWNLOAD_TIMEOUT = 180.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLIB_SECRETS_DIR = _REPO_ROOT / "secrets" / "plib"

# P-Lib's recency filter uses "" for "all"; the schema exposes the friendlier
# all/week/month/year, mapped here to match the site's <select> option values.
_TIME_MAP = {"": "", "all": "", "week": "week", "month": "month", "year": "year"}

# A client factory lets tests inject a fake PlibClient without touching the
# network; production builds a real client per call.
ClientFactory = Callable[[float, "Credentials | None"], PlibClient]


def _default_client_factory(timeout: float, credentials: Credentials | None) -> PlibClient:
    return PlibClient(timeout=timeout, credentials=credentials)


class PLibMaterialsTool(Tool):
    name: ClassVar[str] = "plib_materials"
    description: ClassVar[str] = (
        "Search and inspect P-Lib/PKUHUB course materials. Actions: `login` with "
        "email/password, `search` by keyword, `show` one material by id, `quota` "
        "for remaining daily downloads, and `download` by ids. Use this for "
        "questions like “帮我找高数往年题” or “P-Lib 今天还能下载几次？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["login", "search", "show", "quota", "download"],
                "description": "Which P-Lib operation to run.",
            },
            "email": {
                "type": "string",
                "description": "P-Lib login email. Required for `login`.",
            },
            "password": {
                "type": "string",
                "description": "P-Lib login password. Required for `login`.",
            },
            "query": {
                "type": "string",
                "description": "Search keyword. Required for `search`.",
            },
            "id": {
                "type": "integer",
                "description": "Material id. Required for `show`; accepted by `download`.",
            },
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Material ids for `download`.",
            },
            "type": {
                "type": "string",
                "description": "Optional search type: 习题/其他/汇编/笔记/答案/试卷/课件/课本.",
            },
            "sort": {
                "type": "string",
                "description": (
                    "Optional search sort: "
                    "relevance/newest/downloads/views/likes/title/comments."
                ),
            },
            "time": {
                "type": "string",
                "description": "Optional search time window: all/week/month/year.",
            },
            "limit": {
                "type": "integer",
                "description": "Search result cap. Default 10.",
                "minimum": 1,
                "default": 10,
            },
            "output_dir": {
                "type": "string",
                "description": "Download output directory. Default: downloads/plib.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        secrets_dir: str | Path | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.timeout = timeout
        self.secrets_dir = (
            Path(secrets_dir) if secrets_dir is not None else _PLIB_SECRETS_DIR
        )
        self._client_factory = client_factory or _default_client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip()
        if action == "login":
            return self._login(args)
        if action == "search":
            return self._search(args)
        if action == "show":
            return self._show(args)
        if action == "quota":
            return self._run(lambda c: c.profile().to_dict())
        if action == "download":
            return self._download(args)
        return ToolResult(success=False, error=f"unknown action: {action!r}")

    def _login(self, args: dict[str, Any]) -> ToolResult:
        email = str(args.get("email") or "").strip()
        password = str(args.get("password") or "")
        if not email or not password:
            return ToolResult(success=False, error="`login` requires email and password")

        def call(client: PlibClient) -> dict[str, Any]:
            client.login()
            return {"status": "logged_in", "quota_remaining": client.quota_remaining()}

        return self._run(call, credentials=Credentials(email, password))

    def _search(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, error="`search` requires a non-empty query")
        limit = int(args.get("limit") or 10)
        material_type = str(args.get("type") or "").strip() or None
        sort = str(args.get("sort") or "").strip() or "relevance"
        time_window = _TIME_MAP.get(str(args.get("time") or "").strip(), "")
        return self._run(
            lambda c: c.search_all(
                query, type=material_type, time=time_window, sort=sort, limit=limit
            ).to_dict()
        )

    def _show(self, args: dict[str, Any]) -> ToolResult:
        material_id = args.get("id")
        if not isinstance(material_id, int):
            return ToolResult(success=False, error="`show` requires integer `id`")
        return self._run(lambda c: c.material(material_id).to_dict())

    def _download(self, args: dict[str, Any]) -> ToolResult:
        ids = [item for item in args.get("ids") or [] if isinstance(item, int)]
        if isinstance(args.get("id"), int):
            ids.insert(0, args["id"])
        if not ids:
            return ToolResult(success=False, error="`download` requires `id` or `ids`")
        output_dir = str(args.get("output_dir") or (_REPO_ROOT / "downloads" / "plib"))

        def call(client: PlibClient) -> dict[str, Any]:
            downloads = [client.download(mid, output_dir).to_dict() for mid in ids]
            return {"downloads": downloads, "quota_remaining": client.quota_remaining()}

        return self._run(call, timeout=DOWNLOAD_TIMEOUT)

    def _run(
        self,
        call: Callable[[PlibClient], Any],
        *,
        timeout: float | None = None,
        credentials: Credentials | None = None,
    ) -> ToolResult:
        creds = credentials or self._stored_credentials()
        # Strip the credential values from any error we surface, in case the
        # library echoes them on an auth failure.
        secret_values = [creds.email, creds.password] if creds else []
        try:
            client = self._client_factory(timeout or self.timeout, creds)
            data = call(client)
        except PlibError as exc:
            return ToolResult(success=False, error=redact(str(exc), secret_values))
        return ToolResult(success=True, data=data)

    def _stored_credentials(self) -> Credentials | None:
        """Read stored P-Lib credentials so every call self-authenticates.

        Returns ``None`` when the files are absent, in which case the client
        falls back to its own resolution (env / config dir) — matching the old
        behaviour where an empty credential env let plib self-resolve.
        """
        email = self._read_secret("email")
        password = self._read_secret("password")
        if email and password:
            return Credentials(email, password)
        return None

    def _read_secret(self, name: str) -> str:
        path = self.secrets_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
