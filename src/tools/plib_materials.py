"""P-Lib course-material search via the external ``plib`` CLI.

``plib-cli`` lives at https://github.com/RizzoHou/plib-cli. It has no public
web API behind it, so pku-captain treats it like pku3b: invoke the CLI as a
subprocess and consume its stable JSON envelope.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from .base import Tool, ToolResult
from .redact import redact

# Env keys whose values are P-Lib credentials; redacted from any error string
# before it can reach a ToolResult (and thus the LLM context / session store).
_CREDENTIAL_ENV_KEYS = ("PLIB_EMAIL", "PLIB_PASSWORD")

DEFAULT_EXECUTABLE = "plib"
DEFAULT_TIMEOUT = 60.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _REPO_ROOT.parent
_PLIB_SECRETS_DIR = _REPO_ROOT / "secrets" / "plib"
_LOCAL_EXECUTABLES = (
    _WORKSPACE_ROOT / "plib-cli" / ".venv" / "bin" / "plib",
    _REPO_ROOT / ".local" / "bin" / "plib",
)


class PlibNotFoundError(RuntimeError):
    """Raised when the plib CLI cannot be located."""


class PlibTimeoutError(RuntimeError):
    """Raised when a plib subprocess exceeds its timeout."""


class PLibMaterialsTool(Tool):
    name: ClassVar[str] = "plib_materials"
    description: ClassVar[str] = (
        "Search and inspect P-Lib/PKUHUB course materials via the local `plib` "
        "CLI. Actions: `login` with email/password, `search` by keyword, "
        "`show` one material by id, `quota` for remaining daily downloads, "
        "and `download` by ids. Use this for "
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
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = DEFAULT_TIMEOUT,
        secrets_dir: str | Path | None = None,
    ) -> None:
        self.executable = executable
        self.timeout = timeout
        self.secrets_dir = (
            Path(secrets_dir) if secrets_dir is not None else _PLIB_SECRETS_DIR
        )

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip()
        if action == "login":
            return self._login(args)
        if action == "search":
            return self._search(args)
        if action == "show":
            return self._show(args)
        if action == "quota":
            return self._run_json(["quota"])
        if action == "download":
            return self._download(args)
        return ToolResult(success=False, error=f"unknown action: {action!r}")

    def _login(self, args: dict[str, Any]) -> ToolResult:
        email = str(args.get("email") or "").strip()
        password = str(args.get("password") or "")
        if not email or not password:
            return ToolResult(success=False, error="`login` requires email and password")
        return self._run_json(["login"], env={"PLIB_EMAIL": email, "PLIB_PASSWORD": password})

    def _search(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, error="`search` requires a non-empty query")
        cli_args = ["search", query, "--limit", str(int(args.get("limit") or 10))]
        for key in ("type", "sort", "time"):
            value = str(args.get(key) or "").strip()
            if value:
                cli_args.extend([f"--{key}", value])
        return self._run_json(cli_args)

    def _show(self, args: dict[str, Any]) -> ToolResult:
        material_id = args.get("id")
        if not isinstance(material_id, int):
            return ToolResult(success=False, error="`show` requires integer `id`")
        return self._run_json(["show", str(material_id)])

    def _download(self, args: dict[str, Any]) -> ToolResult:
        ids = [str(item) for item in args.get("ids") or [] if isinstance(item, int)]
        if isinstance(args.get("id"), int):
            ids.insert(0, str(args["id"]))
        if not ids:
            return ToolResult(success=False, error="`download` requires `id` or `ids`")
        output_dir = str(args.get("output_dir") or (_REPO_ROOT / "downloads" / "plib"))
        return self._run_json(["download", *ids, "-o", output_dir], timeout=180.0)

    def _credentials_env(self) -> dict[str, str]:
        """Read stored P-Lib credentials so every call self-authenticates.

        plib resolves ``PLIB_EMAIL`` / ``PLIB_PASSWORD`` first, and its auth is
        self-healing, so injecting the stored account here makes search / quota /
        download work without a manual ``login`` action.
        """
        email = self._read_secret("email")
        password = self._read_secret("password")
        if email and password:
            return {"PLIB_EMAIL": email, "PLIB_PASSWORD": password}
        return {}

    def _read_secret(self, name: str) -> str:
        path = self.secrets_dir / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _run_json(
        self,
        cli_args: Sequence[str],
        *,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ToolResult:
        # Stored credentials form the base; an explicit `login` env overrides.
        merged_env = self._credentials_env()
        if env:
            merged_env.update(env)
        try:
            run = run_plib(
                cli_args,
                executable=self.executable,
                timeout=timeout or self.timeout,
                env=merged_env or None,
            )
        except PlibNotFoundError as exc:
            return ToolResult(success=False, error=str(exc))
        except PlibTimeoutError as exc:
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
    raise PlibNotFoundError(
        f"could not find {executable!r} on PATH or at {locations}. "
        "Install with: git clone https://github.com/RizzoHou/plib-cli && "
        "cd plib-cli && python3 -m venv .venv && .venv/bin/pip install -e ."
    )


def run_plib(
    args: Sequence[str],
    *,
    executable: str = DEFAULT_EXECUTABLE,
    timeout: float = DEFAULT_TIMEOUT,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    binary = resolve_executable(executable)
    argv = [binary, "--format", "json", *args]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    # The credential values we inject — strip them from any error we surface, in
    # case plib echoes them on an auth failure.
    secret_values = [env[key] for key in _CREDENTIAL_ENV_KEYS if env and env.get(key)]
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
            env=process_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise PlibTimeoutError(f"plib {' '.join(args)} timed out after {timeout}s") from exc

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        err = proc.stderr.strip() or proc.stdout.strip() or "invalid JSON output"
        message = f"plib exited {proc.returncode}: {err}"
        return {"ok": False, "error": redact(message, secret_values)}

    if proc.returncode != 0 or not payload.get("ok", False):
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or str(error)
        else:
            message = str(error or proc.stderr.strip() or "plib command failed")
        return {"ok": False, "error": redact(message, secret_values)}
    return {"ok": True, "data": payload.get("data")}
