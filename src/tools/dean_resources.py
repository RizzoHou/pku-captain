"""Public dean.pku.edu.cn resources via the external ``dean`` CLI.

``pku-dean-cli`` lives at https://github.com/RizzoHou/pku-dean-cli. It fetches
**public** resources from PKU's Office of Educational Administration site
(no login required) and exposes the same stable JSON envelope pku-captain
already consumes for ``plib`` / ``pku3b``: ``--format json`` before the
subcommand, ``{"ok": true, "data": ...}`` / ``{"ok": false, "error": {...}}``
always on stdout.

Install the sibling repo next to pku-captain (``~/projects/pku-dean-cli``):

    git clone https://github.com/RizzoHou/pku-dean-cli
    cd pku-dean-cli && python3 -m venv .venv && .venv/bin/pip install -e .

This tool exposes the **read** surface (sidebar, guide, rules, file
listings). The CLI's file-download ``get`` actions (``download get`` /
``openinfo get``) are deliberately **not** exposed in v1 — they write
binaries to disk, a side effect outside this Q&A tool's scope; re-add them
behind an explicit action if a product need appears. ``--all`` (fetch every
page) is also omitted: it walks every page over HTTP and would risk the
subprocess timeout and flood the conversation; callers page with ``page``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult

DEFAULT_EXECUTABLE = "dean"
DEFAULT_TIMEOUT = 60.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _REPO_ROOT.parent
_LOCAL_EXECUTABLES = (
    _WORKSPACE_ROOT / "pku-dean-cli" / ".venv" / "bin" / "dean",
    _REPO_ROOT / ".local" / "bin" / "dean",
)


class DeanNotFoundError(RuntimeError):
    """Raised when the dean CLI cannot be located."""


class DeanTimeoutError(RuntimeError):
    """Raised when a dean subprocess exceeds its timeout."""


class DeanResourcesTool(Tool):
    name: ClassVar[str] = "dean_resources"
    description: ClassVar[str] = (
        "Fetch public resources from PKU's Office of Educational Administration "
        "(教务部, dean.pku.edu.cn) via the local `dean` CLI — no login needed. "
        "Actions: `sidebar` (student-service links by category), `guide` by id "
        "(content behind a sidebar link), `rules_list` (校级/国家 regulations, "
        "scope school|national), `rules_show` by id (full rule text), "
        "`download_list` (downloadable forms/handbooks), `openinfo_list` "
        "(information-disclosure files). `guide` ids come from `sidebar` URLs and "
        "`rules_show` ids from `rules_list`, so list first, then show. Use this "
        "for questions like “选课手册在哪下载”, “本科生学籍管理办法怎么规定的”, or "
        "“教务部最近公示了什么”."
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
                    "download_list",
                    "openinfo_list",
                ],
                "description": "Which dean.pku.edu.cn resource to fetch.",
            },
            "id": {
                "type": "integer",
                "description": "Resource id. Required for `guide` and `rules_show`.",
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
                    "Page number for `rules_list` / `download_list` / "
                    "`openinfo_list`. Default 1. The response carries `last_page`."
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
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.executable = executable
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip()
        if action == "sidebar":
            return self._run_json(["sidebar"])
        if action == "guide":
            return self._show("guide", args)
        if action == "rules_show":
            return self._show("rules", args, subcommand="show")
        if action == "rules_list":
            scope = str(args.get("scope") or "school").strip()
            cli_args = ["rules", "list", "--scope", scope, *self._page(args)]
            return self._run_json(cli_args)
        if action == "download_list":
            return self._run_json(["download", "list", *self._page(args)])
        if action == "openinfo_list":
            return self._run_json(["openinfo", "list", *self._page(args)])
        return ToolResult(success=False, error=f"unknown action: {action!r}")

    def _show(
        self, command: str, args: dict[str, Any], *, subcommand: str | None = None
    ) -> ToolResult:
        resource_id = args.get("id")
        if not isinstance(resource_id, int):
            label = f"{command} {subcommand}" if subcommand else command
            return ToolResult(success=False, error=f"`{label}` requires integer `id`")
        cli_args = [command]
        if subcommand:
            cli_args.append(subcommand)
        cli_args.append(str(resource_id))
        return self._run_json(cli_args)

    @staticmethod
    def _page(args: dict[str, Any]) -> list[str]:
        page = args.get("page")
        if isinstance(page, int) and page > 1:
            return ["--page", str(page)]
        return []

    def _run_json(self, cli_args: Sequence[str]) -> ToolResult:
        try:
            run = run_dean(cli_args, executable=self.executable, timeout=self.timeout)
        except (DeanNotFoundError, DeanTimeoutError) as exc:
            return ToolResult(success=False, error=str(exc))
        if not run["ok"]:
            return ToolResult(success=False, error=run["error"])
        return ToolResult(success=True, data=run["data"])


def resolve_executable(executable: str = DEFAULT_EXECUTABLE) -> str:
    found = shutil.which(executable)
    if found:
        return found
    if executable == DEFAULT_EXECUTABLE:
        for path in _LOCAL_EXECUTABLES:
            if path.exists():
                return str(path)
    locations = ", ".join(str(path) for path in _LOCAL_EXECUTABLES)
    raise DeanNotFoundError(
        f"could not find {executable!r} on PATH or at {locations}. "
        "Install with: git clone https://github.com/RizzoHou/pku-dean-cli && "
        "cd pku-dean-cli && python3 -m venv .venv && .venv/bin/pip install -e ."
    )


def run_dean(
    args: Sequence[str],
    *,
    executable: str = DEFAULT_EXECUTABLE,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run ``dean --format json <args>`` and parse the stable envelope.

    Returns ``{"ok": True, "data": ...}`` or ``{"ok": False, "error": str}``.
    The envelope is parsed from stdout regardless of exit code, mirroring the
    plib wrapper — the CLI writes ``{"ok": false, ...}`` on failure too.
    """
    binary = resolve_executable(executable)
    argv = [binary, "--format", "json", *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            cwd=_REPO_ROOT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise DeanTimeoutError(f"dean {' '.join(args)} timed out after {timeout}s") from exc

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        err = proc.stderr.strip() or proc.stdout.strip() or "invalid JSON output"
        return {"ok": False, "error": f"dean exited {proc.returncode}: {err}"}

    if proc.returncode != 0 or not payload.get("ok", False):
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or str(error)
        else:
            message = str(error or proc.stderr.strip() or "dean command failed")
        return {"ok": False, "error": message}
    return {"ok": True, "data": payload.get("data")}
