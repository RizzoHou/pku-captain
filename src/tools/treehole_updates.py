"""PKU Treehole update monitor tool.

This tool wraps the local ``pku-treehole-cli`` library and exposes one
conservative operation for the agent/GUI: check whether watched or followed
holes gained replies since the last baseline.
"""

from __future__ import annotations

import json
import math
import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import requests

from .base import Tool, ToolResult

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _REPO_ROOT.parent
_TREEHOLE_SRC = _WORKSPACE_ROOT / "pku-treehole-cli" / "src"
if _TREEHOLE_SRC.exists() and str(_TREEHOLE_SRC) not in sys.path:
    sys.path.insert(0, str(_TREEHOLE_SRC))

try:  # pragma: no cover - exercised through normal imports when available.
    from treehole.app import build_client, build_monitor
    from treehole.auth import Credentials, login
    from treehole.errors import AuthError, NeedSMSVerification, TreeholeError
    from treehole.session import SessionStore
except ModuleNotFoundError:  # pragma: no cover - covered by graceful runtime error.
    build_client = None  # type: ignore[assignment]
    build_monitor = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    login = None  # type: ignore[assignment]
    SessionStore = None  # type: ignore[assignment]

    class TreeholeError(Exception):
        pass

    class AuthError(TreeholeError):
        pass

    class NeedSMSVerification(AuthError):  # noqa: N818 - mirrors treehole library name.
        pass


ClientFactory = Callable[..., Any]
MonitorFactory = Callable[..., Any]


class TreeholeAuthService:
    """Small GUI-facing wrapper for treehole login and SMS verification."""

    def __init__(self, *, secrets_dir: str | Path | None = None) -> None:
        base = _REPO_ROOT / "secrets" / "treehole"
        self.secrets_dir = Path(secrets_dir) if secrets_dir is not None else base
        self.session_path = self.secrets_dir / "session.json"

    def status(self) -> dict[str, object]:
        if build_client is None:
            return {"ok": False, "message": "树洞库不可用"}
        if not self.session_path.exists():
            return {"ok": False, "message": "尚未登录树洞"}
        try:
            me = build_client(self.secrets_dir, allow_relogin=False).users_info()
        except NeedSMSVerification:
            return {"ok": False, "message": "需要短信验证"}
        except AuthError as exc:
            return {"ok": False, "message": f"登录状态不可用：{exc}"}
        except TreeholeError as exc:
            return {"ok": False, "message": f"树洞接口错误：{exc}"}
        except requests.exceptions.RequestException:
            return {"ok": False, "message": "网络不可用，无法检查登录状态"}
        return {
            "ok": True,
            "message": "树洞已登录",
            "uid": me.get("uid"),
            "name": me.get("name"),
            "department": me.get("department"),
            "newmsgcount": me.get("newmsgcount"),
        }

    def login(self, uid: str, password: str, *, otp: str = "") -> dict[str, object]:
        if login is None or Credentials is None or SessionStore is None:
            return {"ok": False, "message": "树洞库不可用"}
        uid = uid.strip()
        if not uid or not password:
            return {"ok": False, "message": "账号和密码不能为空"}
        try:
            self.secrets_dir.mkdir(parents=True, exist_ok=True)
            (self.secrets_dir / "id").write_text(uid)
            (self.secrets_dir / "password").write_text(password)
            store = SessionStore(self.session_path)
            existing = store.load_or_none()
            identity = login(
                Credentials(uid=uid, password=password),
                login_uuid=existing.login_uuid if existing else None,
                otp=otp.strip(),
            )
            store.save(identity)
        except AuthError as exc:
            return {"ok": False, "message": f"登录失败：{exc}"}
        except TreeholeError as exc:
            return {"ok": False, "message": f"登录失败：{exc}"}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": f"网络错误：{exc}"}
        except OSError as exc:
            return {"ok": False, "message": f"保存登录状态失败：{exc}"}
        return {"ok": True, "message": "登录成功，请发送短信验证码并完成验证"}

    def send_sms(self) -> dict[str, object]:
        if build_client is None:
            return {"ok": False, "message": "树洞库不可用"}
        try:
            build_client(self.secrets_dir, allow_relogin=False).send_sms()
        except AuthError as exc:
            return {"ok": False, "message": f"无法发送验证码：{exc}"}
        except TreeholeError as exc:
            return {"ok": False, "message": f"无法发送验证码：{exc}"}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": f"网络错误：{exc}"}
        return {"ok": True, "message": "验证码已发送，请查看绑定手机号"}

    def verify_sms(self, code: str) -> dict[str, object]:
        if build_client is None:
            return {"ok": False, "message": "树洞库不可用"}
        code = code.strip()
        if not code:
            return {"ok": False, "message": "验证码不能为空"}
        try:
            build_client(self.secrets_dir, allow_relogin=False).verify_sms(code)
        except AuthError as exc:
            return {"ok": False, "message": f"验证失败：{exc}"}
        except TreeholeError as exc:
            return {"ok": False, "message": f"验证失败：{exc}"}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": f"网络错误：{exc}"}
        return {"ok": True, "message": "短信验证完成，现在可以读取树洞消息"}


DEFAULT_NOTIFY_INTERVAL = 60
MIN_NOTIFY_INTERVAL = 30

# The standalone daemon and notifier live in pku-treehole-cli; we drive them via
# its venv entrypoint. pku-captain's own venv does not install the `treehole`
# package (TreeholeUpdatesTool imports it via a sys.path shim, in-process).
_TREEHOLE_VENV_BIN = _WORKSPACE_ROOT / "pku-treehole-cli" / ".venv" / "bin" / "treehole"

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _find_treehole_bin() -> Path | None:
    if _TREEHOLE_VENV_BIN.exists():
        return _TREEHOLE_VENV_BIN
    found = shutil.which("treehole")
    return Path(found) if found else None


def _default_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)  # noqa: S603


def _format_interval(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600} 小时"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


def _launchctl_error(cmd: list[str], result: subprocess.CompletedProcess[str]) -> str:
    label = " ".join(cmd[:2])
    detail = (getattr(result, "stderr", "") or "").strip()
    base = f"{label} 失败（退出码 {result.returncode}）"
    return f"{base}：{detail}" if detail else base


class TreeholeNotificationService:
    """Manage the macOS LaunchAgent that polls Treehole and posts desktop
    notifications, reusing pku-captain's own login session.

    A GUI-facing sibling to ``TreeholeAuthService`` — deliberately **not** a
    ``Tool`` subclass, because it manages OS state (a per-user LaunchAgent), not
    an agent-callable operation. We own a distinct label
    (``com.pku.captain.treehole.notify``) and point the daemon at
    ``secrets/treehole`` so a single GUI login drives both the dashboard and the
    background notifier. The plist + launchctl sequence is ported from
    ``pku-treehole-cli/macos/install-agent.sh``; that script stays the standalone
    reference. macOS-only (delivery is osascript); off macOS every method returns
    a clear unsupported result rather than raising.
    """

    LABEL: ClassVar[str] = "com.pku.captain.treehole.notify"
    _DAEMON_PATH: ClassVar[str] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    def __init__(
        self,
        *,
        secrets_dir: str | Path | None = None,
        treehole_bin: str | Path | None = None,
        state_path: str | Path | None = None,
        settings_path: str | Path | None = None,
        log_dir: str | Path | None = None,
        launch_agents_dir: str | Path | None = None,
        runner: Runner | None = None,
        platform_name: str | None = None,
        uid: int | None = None,
    ) -> None:
        self._repo_root = _REPO_ROOT
        base = _REPO_ROOT / "secrets" / "treehole"
        data_dir = _REPO_ROOT / "data"
        self.secrets_dir = Path(secrets_dir) if secrets_dir is not None else base
        self.session_path = self.secrets_dir / "session.json"
        self.state_path = (
            Path(state_path) if state_path is not None else data_dir / "treehole-notify-state.json"
        )
        self.settings_path = (
            Path(settings_path) if settings_path is not None else data_dir / "treehole_notify.json"
        )
        self._log_dir = Path(log_dir) if log_dir is not None else data_dir
        self._launch_agents_dir = (
            Path(launch_agents_dir)
            if launch_agents_dir is not None
            else Path.home() / "Library" / "LaunchAgents"
        )
        provided_bin = Path(treehole_bin) if treehole_bin is not None else _find_treehole_bin()
        self._treehole_bin: Path | None = provided_bin
        self._runner: Runner = runner if runner is not None else _default_runner
        self._platform = platform_name if platform_name is not None else sys.platform
        self._uid = uid  # resolved lazily so construction never calls os.getuid off-platform.

    # --- capabilities ---------------------------------------------------------
    def is_supported(self) -> bool:
        return self._platform == "darwin"

    def binary_available(self) -> bool:
        return self._treehole_bin is not None and Path(self._treehole_bin).exists()

    def is_logged_in(self) -> bool:
        return self.session_path.exists()

    def is_enabled(self) -> bool:
        return self._plist_path().exists()

    # --- interval preference --------------------------------------------------
    def get_interval(self) -> int:
        try:
            data = json.loads(self.settings_path.read_text())
            value = int(data["interval"])
        except (OSError, ValueError, TypeError, KeyError):
            return DEFAULT_NOTIFY_INTERVAL
        return value if value >= MIN_NOTIFY_INTERVAL else DEFAULT_NOTIFY_INTERVAL

    def set_interval(self, interval_seconds: int) -> dict[str, object]:
        interval = self._normalize_interval(interval_seconds)
        if self.is_supported() and self.is_enabled():
            # Already running — re-install so the new cadence takes effect now.
            return self.enable(interval)
        try:
            self._save_interval(interval)
        except OSError as exc:
            return {"ok": False, "message": f"保存设置失败：{exc}"}
        return {
            "ok": True,
            "interval": interval,
            "message": f"检查间隔已设为每 {_format_interval(interval)}",
        }

    # --- status ---------------------------------------------------------------
    def status(self) -> dict[str, object]:
        supported = self.is_supported()
        binary = self.binary_available()
        enabled = self.is_enabled() if supported else False
        interval = self.get_interval()
        if not supported:
            message = "系统通知仅支持 macOS"
        elif not binary:
            message = "未找到 treehole 程序：请先安装 pku-treehole-cli（见 docs/setup_zh.md）"
        elif enabled:
            message = f"通知已开启 · 每 {_format_interval(interval)} 检查一次"
        else:
            message = "通知未开启"
        return {
            "supported": supported,
            "binary_available": binary,
            "logged_in": self.is_logged_in(),
            "enabled": enabled,
            "interval": interval,
            "message": message,
        }

    # --- enable / disable -----------------------------------------------------
    def enable(self, interval_seconds: int | None = None) -> dict[str, object]:
        if not self.is_supported():
            return {"ok": False, "message": "系统通知仅支持 macOS"}
        if not self.binary_available():
            return {
                "ok": False,
                "message": "未找到 treehole 程序：请先安装 pku-treehole-cli（见 docs/setup_zh.md）",
            }
        interval = self._normalize_interval(
            interval_seconds if interval_seconds is not None else self.get_interval()
        )
        plist_path = self._plist_path()
        try:
            self._save_interval(interval)
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(plistlib.dumps(self._plist_dict(interval)))
        except OSError as exc:
            return {"ok": False, "message": f"写入启动项失败：{exc}"}

        domain = self._domain()
        target = f"{domain}/{self.LABEL}"
        # bootout first (ignore failure if not loaded) so re-enabling with a new
        # interval reloads cleanly instead of erroring on a duplicate label.
        self._run(["launchctl", "bootout", target])
        for cmd in (
            ["launchctl", "bootstrap", domain, str(plist_path)],
            ["launchctl", "enable", target],
            ["launchctl", "kickstart", target],
        ):
            result = self._run(cmd)
            if result.returncode != 0:
                return {"ok": False, "interval": interval, "message": _launchctl_error(cmd, result)}

        note = (
            ""
            if self.is_logged_in()
            else "（提示：尚未登录树洞，后台通知将无法获取消息，请先在「树洞账户」中登录）"
        )
        return {
            "ok": True,
            "interval": interval,
            "message": f"已开启树洞消息通知 · 每 {_format_interval(interval)} 检查一次{note}",
        }

    def disable(self) -> dict[str, object]:
        if not self.is_supported():
            return {"ok": False, "message": "系统通知仅支持 macOS"}
        self._run(["launchctl", "bootout", f"{self._domain()}/{self.LABEL}"])
        try:
            self._plist_path().unlink(missing_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"移除启动项失败：{exc}"}
        return {"ok": True, "message": "已关闭树洞消息通知"}

    # --- internals ------------------------------------------------------------
    def _normalize_interval(self, value: object) -> int:
        try:
            seconds = int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return DEFAULT_NOTIFY_INTERVAL
        return max(MIN_NOTIFY_INTERVAL, seconds)

    def _save_interval(self, interval: int) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"interval": int(interval)}))

    def _plist_path(self) -> Path:
        return self._launch_agents_dir / f"{self.LABEL}.plist"

    def _domain(self) -> str:
        uid = self._uid if self._uid is not None else os.getuid()
        return f"gui/{uid}"

    def _plist_dict(self, interval: int) -> dict[str, object]:
        return {
            "Label": self.LABEL,
            "ProgramArguments": [
                str(self._treehole_bin),
                "--secrets-dir",
                str(self.secrets_dir),
                "monitor",
                "--state",
                str(self.state_path),
                "--notify",
            ],
            "WorkingDirectory": str(self._repo_root),
            "StartInterval": int(interval),
            "RunAtLoad": True,
            "ProcessType": "Background",
            "EnvironmentVariables": {"PATH": self._DAEMON_PATH},
            "StandardOutPath": str(self._log_dir / "treehole-notify.out.log"),
            "StandardErrorPath": str(self._log_dir / "treehole-notify.err.log"),
        }

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return self._runner(list(cmd))


def merge_treehole_updates(
    existing: list[dict[str, Any]], new_updates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Accumulate treehole updates by ``pid`` so the dashboard keeps unread
    replies visible instead of dropping them on the next (empty) poll.

    Each ``monitor.check()`` only returns the delta *since the dashboard's last
    poll*, so replacing the card with each poll makes a new reply vanish after
    one interval. Merging instead keeps every unread hole until the user views
    it: ``new_comments`` are unioned by ``cid`` (oldest-first), ``old_reply`` is
    the earliest baseline first seen, ``new_reply`` the latest count, and
    ``delta`` is derived so it never undercounts the comments we can show
    (``hidden = delta - shown`` stays >= 0). Pure and order-independent within a
    poll batch; idempotent on re-merging an already-accumulated list.
    """
    merged: dict[str, dict[str, Any]] = {}
    cids: dict[str, dict[int, dict[str, Any]]] = {}
    order: list[str] = []

    def _absorb(entry: dict[str, Any]) -> None:
        raw_pid = entry.get("pid")
        if raw_pid is None:
            return
        pid = str(raw_pid)
        cur = merged.get(pid)
        if cur is None:
            cur = {
                "pid": pid,
                "old_reply": int(entry.get("old_reply") or 0),
                "new_reply": int(entry.get("new_reply") or 0),
                "text": entry.get("text"),
            }
            merged[pid] = cur
            cids[pid] = {}
            order.append(pid)
        else:
            cur["old_reply"] = min(cur["old_reply"], int(entry.get("old_reply") or 0))
            cur["new_reply"] = max(cur["new_reply"], int(entry.get("new_reply") or 0))
            if entry.get("text"):
                cur["text"] = entry.get("text")
        for comment in entry.get("new_comments") or []:
            if not isinstance(comment, dict) or comment.get("cid") is None:
                continue
            cids[pid][int(comment["cid"])] = comment

    for entry in list(existing or []) + list(new_updates or []):
        if isinstance(entry, dict):
            _absorb(entry)

    result: list[dict[str, Any]] = []
    for pid in order:
        cur = merged[pid]
        comments = [cids[pid][key] for key in sorted(cids[pid])]
        delta = max(cur["new_reply"] - cur["old_reply"], len(comments), 0)
        result.append({
            "pid": pid,
            "old_reply": cur["old_reply"],
            "new_reply": cur["new_reply"],
            "delta": delta,
            "text": cur["text"],
            "new_comments": comments,
        })
    result.sort(key=lambda item: int(item.get("new_reply") or 0), reverse=True)
    return result


class TreeholeInboxStore:
    """Persisted accumulator of unread treehole updates feeding the dashboard.

    The dashboard re-derives unread replies from its own ``monitor.check()``
    poll (a separate baseline from the background notifier's), so this store is
    what makes those polls *stick*: each poll's updates are merged in and the
    set survives until the user opens the messages dialog (mark-as-read →
    ``clear``). Persisting to ``data/treehole_inbox.json`` lets an unviewed
    reply survive an app restart — on reopen the startup poll re-derives
    anything that arrived while closed (the dashboard's state cursor is frozen
    while the app is shut), and merges it back in.

    ``path=None`` keeps it in-memory (the GUI default and tests use this so they
    never touch the repo's ``data/``); ``MainWindow`` injects a real path.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        entries = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries if isinstance(entry, dict)]

    def entries(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._entries]

    def unread_count(self) -> int:
        return sum(int(entry.get("delta") or 0) for entry in self._entries)

    def merge(self, updates: list[dict[str, Any]]) -> None:
        self._entries = merge_treehole_updates(self._entries, list(updates or []))
        self._save()

    def clear(self) -> None:
        if not self._entries:
            return
        self._entries = []
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"entries": self._entries}, ensure_ascii=False)
            )
        except OSError:
            pass


class TreeholeUpdatesTool(Tool):
    name: ClassVar[str] = "treehole_updates"
    description: ClassVar[str] = (
        "Check PKU Treehole followed/watched holes for newly added replies. "
        "Returns a baseline status, unread reply count, and recent new comment "
        "text when available. Use it for questions like “树洞有新消息吗？”."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "holes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional pid list to check directly instead of all followed holes.",
            },
            "fetch_comments": {
                "type": "boolean",
                "description": "Whether to fetch new comment text. Default: true.",
                "default": True,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of updated holes returned. Default: 5.",
                "minimum": 1,
                "default": 5,
            },
            "allow_relogin": {
                "type": "boolean",
                "description": (
                    "Allow the treehole library to re-login once on 401 when credentials exist. "
                    "Default: false to avoid consuming IAAA attempts from the GUI."
                ),
                "default": False,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        secrets_dir: str | Path | None = None,
        state_path: str | Path | None = None,
        monitor_factory: MonitorFactory | None = None,
    ) -> None:
        base = _REPO_ROOT / "secrets" / "treehole"
        self.secrets_dir = Path(secrets_dir) if secrets_dir is not None else base
        self.state_path = Path(state_path) if state_path is not None else base / "state.json"
        self._monitor_factory = monitor_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        if build_monitor is None and self._monitor_factory is None:
            return ToolResult(
                success=False,
                error=(
                    "树洞库不可用：未找到 pku-treehole-cli。请确认工作区包含 "
                    "pku-treehole-cli，或安装 pku-treehole 包。"
                ),
            )

        try:
            monitor = self._build_monitor(args)
            holes = _normalize_holes(args.get("holes"))
            updates = monitor.check(
                only=holes,
                fetch_comments=bool(args.get("fetch_comments", True)),
            )
        except NeedSMSVerification as exc:
            return _status_result("needs_sms", f"需要短信验证：{exc}")
        except AuthError as exc:
            return _status_result("auth_required", f"树洞登录状态不可用：{exc}")
        except requests.exceptions.RequestException as exc:
            return _status_result("network_error", f"树洞网络请求失败：{exc}")
        except TreeholeError as exc:
            return _status_result("error", f"树洞接口错误：{exc}")
        except OSError as exc:
            return _status_result("error", f"树洞状态文件不可用：{exc}")

        payload = [_update_to_dict(item) for item in updates]
        limit = int(args.get("limit") or 5)
        unread_count = sum(int(item.get("delta") or 0) for item in payload)
        status = "has_updates" if unread_count else "ok"
        return ToolResult(
            success=True,
            data={
                "status": status,
                "message": f"有 {unread_count} 条树洞新回复" if unread_count else "暂无树洞新回复",
                "unread_count": unread_count,
                "updates": payload[:limit],
                "total_updated_holes": len(payload),
                "baseline_only": False,
            },
        )

    def _build_monitor(self, args: dict[str, Any]) -> Any:
        factory = self._monitor_factory or build_monitor
        return factory(
            self.secrets_dir,
            state_path=self.state_path,
            allow_relogin=bool(args.get("allow_relogin", False)),
        )


class TreeholeTool(Tool):
    name: ClassVar[str] = "treehole"
    description: ClassVar[str] = (
        "Search PKU Treehole holes by a small number of space-separated keywords "
        "or fetch one hole with a bounded recent-comment preview. For search, keep "
        "keywords short; this tool splits whitespace keywords, searches at most "
        "three terms, merges candidates, and ranks by relevance, replies, and likes."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "fetch"],
                "description": "`search` by keyword, or `fetch` one hole by pid.",
            },
            "keyword": {
                "type": "string",
                "description": (
                    "Keywords for `search`, separated by spaces. Use at most a few "
                    "short terms; long sentences are split and trimmed by the tool."
                ),
            },
            "pid": {
                "type": "string",
                "description": "Treehole pid for `fetch`.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum returned search rows or fetched recent comments. "
                    "Default: 10 for search, 8 for fetch."
                ),
                "minimum": 1,
                "maximum": 20,
                "default": 10,
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "latest", "hottest", "likes"],
                "description": (
                    "Search ranking mode. Default relevance combines keyword match, "
                    "reply count, like count, and freshness."
                ),
                "default": "relevance",
            },
            "category": {
                "type": "string",
                "enum": [
                    "课程/考试",
                    "二手/交易",
                    "失物招领",
                    "校园生活",
                    "情感/吐槽",
                    "通知/求助",
                    "其他",
                ],
                "description": "Optional lightweight category filter for search results.",
            },
            "comment_mode": {
                "type": "string",
                "enum": ["recent", "none"],
                "description": "For fetch: return recent comments or no comments. Default: recent.",
                "default": "recent",
            },
            "all": {
                "type": "boolean",
                "description": (
                    "Deprecated for agent use. Full pagination is ignored so tool "
                    "results stay within context."
                ),
                "default": False,
            },
            "allow_relogin": {
                "type": "boolean",
                "description": (
                    "Allow pku-treehole-cli to re-login once on 401 when credentials exist. "
                    "Default: false to avoid consuming IAAA attempts from the GUI."
                ),
                "default": False,
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        secrets_dir: str | Path | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        base = _REPO_ROOT / "secrets" / "treehole"
        self.secrets_dir = Path(secrets_dir) if secrets_dir is not None else base
        self._client_factory = client_factory

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        if build_client is None and self._client_factory is None:
            return ToolResult(
                success=False,
                error=(
                    "树洞库不可用：未找到 pku-treehole-cli。请确认工作区包含 "
                    "pku-treehole-cli，或安装 pku-treehole 包。"
                ),
            )

        action = str(args.get("action") or "").strip()
        if action == "search":
            return self._search(args)
        if action == "fetch":
            return self._fetch(args)
        return ToolResult(success=False, error="`action` must be `search` or `fetch`")

    def _search(self, args: dict[str, Any]) -> ToolResult:
        raw_keyword = str(args.get("keyword") or "").strip()
        keywords, ignored_keywords = _split_treehole_keywords(raw_keyword)
        if not keywords:
            return ToolResult(success=False, error="`search` requires a non-empty keyword")
        limit = _bounded_int(args.get("limit"), default=10, minimum=1, maximum=20)
        sort = _normalize_sort(args.get("sort"))
        category = str(args.get("category") or "").strip()
        per_keyword_limit = limit
        try:
            client = self._build_client(args)
            raw_results: list[dict[str, Any]] = []
            for keyword in keywords:
                data = client.search(keyword, limit=per_keyword_limit)
                raw_results.extend(
                    item for item in (data.get("list") or []) if isinstance(item, dict)
                )
        except NeedSMSVerification as exc:
            return _treehole_action_status("needs_sms", f"需要短信验证：{exc}")
        except AuthError as exc:
            return _treehole_action_status("auth_required", f"树洞登录状态不可用：{exc}")
        except requests.exceptions.RequestException as exc:
            return _treehole_action_status("network_error", f"树洞网络请求失败：{exc}")
        except TreeholeError as exc:
            return _treehole_action_status("error", f"树洞接口错误：{exc}")
        except OSError as exc:
            return _treehole_action_status("error", f"树洞状态文件不可用：{exc}")

        ranked = _rank_treehole_results(raw_results, keywords, sort=sort)
        if category:
            ranked = [
                item
                for item in ranked
                if _classify_treehole(str(item.get("text") or "")) == category
            ]
        payload = {
                "status": "ok",
                "action": "search",
                "keyword": " ".join(keywords),
                "keywords": keywords,
                "ignored_keywords": ignored_keywords,
                "sort": sort,
                "category": category,
                "message": f"树洞搜索返回 {min(len(ranked), limit)} 条候选",
                "results": [_hole_to_summary(item, keywords) for item in ranked[:limit]],
                "total_candidates": len(ranked),
                "next_action_hint": (
                    "如需详情，请选择一个 pid 调用 fetch；不要继续扩大关键词反复搜索。"
                ),
        }
        return ToolResult(success=True, data=_fit_treehole_payload(payload))

    def _fetch(self, args: dict[str, Any]) -> ToolResult:
        pid = str(args.get("pid") or "").strip().lstrip("#")
        if not pid:
            return ToolResult(success=False, error="`fetch` requires a non-empty pid")
        limit = _bounded_int(args.get("limit"), default=8, minimum=1, maximum=20)
        comment_mode = str(args.get("comment_mode") or "recent").strip()
        try:
            client = self._build_client(args)
            hole = client.hole(pid)
            comments = (
                []
                if comment_mode == "none"
                else _fetch_recent_comments(client, pid, hole, limit=limit)
            )
        except NeedSMSVerification as exc:
            return _treehole_action_status("needs_sms", f"需要短信验证：{exc}")
        except AuthError as exc:
            return _treehole_action_status("auth_required", f"树洞登录状态不可用：{exc}")
        except requests.exceptions.RequestException as exc:
            return _treehole_action_status("network_error", f"树洞网络请求失败：{exc}")
        except TreeholeError as exc:
            return _treehole_action_status("error", f"树洞接口错误：{exc}")
        except OSError as exc:
            return _treehole_action_status("error", f"树洞状态文件不可用：{exc}")

        payload = {
                "status": "ok",
                "action": "fetch",
                "pid": pid,
                "comment_mode": comment_mode,
                "message": f"树洞 #{pid} 返回最近 {len(comments)} 条评论摘要",
                "hole": _hole_to_summary(hole, []),
                "comments": [_comment_to_summary(item) for item in comments],
                "comment_count": int(hole.get("reply") or len(comments) or 0),
                "returned_comments": len(comments),
                "truncated": int(hole.get("reply") or 0) > len(comments),
        }
        return ToolResult(success=True, data=_fit_treehole_payload(payload))

    def _build_client(self, args: dict[str, Any]) -> Any:
        factory = self._client_factory or build_client
        return factory(
            self.secrets_dir,
            allow_relogin=bool(args.get("allow_relogin", False)),
        )


def _normalize_holes(value: object) -> set[str] | None:
    if value in (None, "", []):
        return None
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return None


def _status_result(status: str, message: str) -> ToolResult:
    return ToolResult(
        success=True,
        data={
            "status": status,
            "message": message,
            "unread_count": 0,
            "updates": [],
            "total_updated_holes": 0,
            "baseline_only": status == "ok",
        },
    )


def _treehole_action_status(status: str, message: str) -> ToolResult:
    return ToolResult(
        success=True,
        data={
            "status": status,
            "message": message,
            "results": [],
            "comments": [],
        },
    )


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


_MAX_TREEHOLE_KEYWORDS = 3
_KEYWORD_RE = re.compile(r"[^\s,，;；、]+")


def _split_treehole_keywords(text: str) -> tuple[list[str], list[str]]:
    """Treehole search works best with a few whitespace-separated keywords."""
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _KEYWORD_RE.findall(text):
        token = match.strip()
        key = token.casefold()
        if not token or key in seen:
            continue
        seen.add(key)
        tokens.append(token[:24])
    return tokens[:_MAX_TREEHOLE_KEYWORDS], tokens[_MAX_TREEHOLE_KEYWORDS:]


def _normalize_sort(value: object) -> str:
    sort = str(value or "relevance").strip()
    return sort if sort in {"relevance", "latest", "hottest", "likes"} else "relevance"


def _rank_treehole_results(
    results: list[dict[str, Any]], keywords: list[str], *, sort: str = "relevance"
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in results:
        pid = str(item.get("pid") or "").strip()
        if not pid:
            continue
        current = merged.get(pid)
        if current is None or _treehole_score(item, keywords) > _treehole_score(current, keywords):
            merged[pid] = item
    if sort == "latest":
        def key(item: dict[str, Any]) -> tuple[int, float]:
            return (int(item.get("timestamp") or 0), _treehole_score(item, keywords))
    elif sort == "hottest":
        def key(item: dict[str, Any]) -> tuple[int, int]:
            return (int(item.get("reply") or 0), int(item.get("likenum") or 0))
    elif sort == "likes":
        def key(item: dict[str, Any]) -> tuple[int, int]:
            return (int(item.get("likenum") or 0), int(item.get("reply") or 0))
    else:
        def key(item: dict[str, Any]) -> tuple[float, int, int]:
            return (
                _treehole_score(item, keywords),
                int(item.get("reply") or 0),
                int(item.get("likenum") or 0),
            )
    return sorted(
        merged.values(),
        key=key,
        reverse=True,
    )


def _treehole_score(item: dict[str, Any], keywords: list[str]) -> float:
    text = str(item.get("text") or "").casefold()
    relevance = sum(1.0 for keyword in keywords if keyword.casefold() in text)
    reply = max(0, int(item.get("reply") or 0))
    like = max(0, int(item.get("likenum") or 0))
    freshness = _freshness_score(item.get("timestamp"))
    return (
        relevance * 10
        + math.log1p(reply) * 0.25
        + math.log1p(like) * 0.35
        + freshness * 0.15
    )


def _freshness_score(value: object) -> float:
    try:
        timestamp = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if timestamp <= 0:
        return 0.0
    age_days = max(0.0, (_now_timestamp() - timestamp) / 86_400)
    return 1.0 / (1.0 + age_days)


def _now_timestamp() -> int:
    import time

    return int(time.time())


def _hole_to_summary(item: object, keywords: list[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    text = str(item.get("text") or "")
    summary = {
        "pid": str(item.get("pid") or ""),
        "text": _clip_text(text, 260),
        "category": _classify_treehole(text),
        "reply": int(item.get("reply") or 0),
        "likenum": int(item.get("likenum") or 0),
        "timestamp": item.get("timestamp"),
    }
    if keywords:
        summary["score"] = round(_treehole_score(item, keywords), 3)
        summary["matched_keywords"] = [
            keyword for keyword in keywords if keyword.casefold() in text.casefold()
        ]
    return summary


def _comment_to_summary(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    quote = item.get("quote") if isinstance(item.get("quote"), dict) else None
    return {
        "cid": item.get("cid"),
        "text": _clip_text(str(item.get("text") or ""), 220),
        "name_tag": item.get("name_tag"),
        "timestamp": item.get("timestamp"),
        "quote": _clip_text(str(quote.get("text") or ""), 80) if quote else "",
    }


def _fetch_recent_comments(
    client: Any, pid: str, hole: dict[str, Any], *, limit: int
) -> list[dict[str, Any]]:
    reply_count = int(hole.get("reply") or 0)
    if reply_count <= 0:
        return []
    page_size = max(limit, 10)
    page = max(1, math.ceil(reply_count / page_size))
    comments = client.comments(pid, page=page, limit=page_size)
    while not comments and page > 1:
        page -= 1
        comments = client.comments(pid, page=page, limit=page_size)
    return [item for item in comments[-limit:] if isinstance(item, dict)]


def _clip_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 8)].rstrip() + "…"


def _classify_treehole(text: str) -> str:
    lowered = text.casefold()
    categories = (
        ("课程/考试", ("考试", "课程", "作业", "绩点", "期末", "选课", "老师")),
        ("二手/交易", ("出", "收", "二手", "转让", "价格", "自取", "闲置")),
        ("失物招领", ("丢", "捡", "遗失", "失物", "招领", "寻找")),
        ("校园生活", ("食堂", "宿舍", "燕园", "校园", "校车", "图书馆")),
        ("情感/吐槽", ("喜欢", "恋爱", "分手", "吐槽", "难过", "焦虑")),
        ("通知/求助", ("通知", "公告", "报名", "讲座", "求助", "请问", "有没有", "怎么", "咨询")),
    )
    for label, markers in categories:
        if any(marker in lowered for marker in markers):
            return label
    return "其他"


_TREEHOLE_RESULT_MAX_CHARS = 6_000


def _fit_treehole_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fitted = dict(payload)
    for key in ("results", "comments"):
        values = fitted.get(key)
        if isinstance(values, list):
            fitted[key] = list(values)
    while _json_size(fitted) > _TREEHOLE_RESULT_MAX_CHARS:
        comments = fitted.get("comments")
        results = fitted.get("results")
        if isinstance(comments, list) and comments:
            comments.pop()
            fitted["returned_comments"] = len(comments)
            fitted["truncated"] = True
            continue
        if isinstance(results, list) and results:
            results.pop()
            fitted["truncated"] = True
            continue
        hole = fitted.get("hole")
        if isinstance(hole, dict) and len(str(hole.get("text") or "")) > 80:
            hole["text"] = _clip_text(str(hole.get("text") or ""), 80)
            fitted["truncated"] = True
            continue
        break
    return fitted


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _update_to_dict(update: object) -> dict[str, Any]:
    if hasattr(update, "to_dict"):
        data = update.to_dict()
    else:
        data = dict(update) if isinstance(update, dict) else {}
    comments = data.get("new_comments")
    if not isinstance(comments, list):
        comments = []
    data["new_comments"] = [
        comment.to_dict() if hasattr(comment, "to_dict") else dict(comment)
        for comment in comments
        if isinstance(comment, dict) or hasattr(comment, "to_dict")
    ]
    return data
