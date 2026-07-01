"""PKU Treehole update monitor tool.

This tool wraps the local ``pku-treehole-cli`` library and exposes one
conservative operation for the agent/GUI: check whether watched or followed
holes gained replies since the last baseline.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import requests

from .base import Tool, ToolResult
from .redact import redact

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ``pku-treehole-cli`` is vendored under vendor/pku-treehole-cli (git subtree)
# and installed as the top-level ``treehole`` package, so it imports directly —
# no sibling-checkout sys.path shim. The try/except keeps a graceful runtime
# error if the package is somehow unavailable (e.g. an install skipped).
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

    def _secret_values(self) -> list[str]:
        """Stored IAAA credentials, to strip from any error before it surfaces."""
        values: list[str] = []
        for name in ("id", "password"):
            path = self.secrets_dir / name
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    values.append(value)
        return values

    def _redact(self, message: str, *extra: str) -> str:
        """Redact stored (and any in-scope) credentials from a message.

        Treehole library exceptions are interpolated into user-facing messages
        that flow into tool results / the conversation; a credential echoed in
        an AuthError would otherwise reach the LLM context and disk.
        """
        return redact(message, [*self._secret_values(), *extra])

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
            return {"ok": False, "message": self._redact(f"登录状态不可用：{exc}")}
        except TreeholeError as exc:
            return {"ok": False, "message": self._redact(f"树洞接口错误：{exc}")}
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
            return {"ok": False, "message": self._redact(f"登录失败：{exc}", uid, password)}
        except TreeholeError as exc:
            return {"ok": False, "message": self._redact(f"登录失败：{exc}", uid, password)}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": self._redact(f"网络错误：{exc}", uid, password)}
        except OSError as exc:
            return {
                "ok": False,
                "message": self._redact(f"保存登录状态失败：{exc}", uid, password),
            }
        return {"ok": True, "message": "登录成功，请发送短信验证码并完成验证"}

    def send_sms(self) -> dict[str, object]:
        if build_client is None:
            return {"ok": False, "message": "树洞库不可用"}
        try:
            build_client(self.secrets_dir, allow_relogin=False).send_sms()
        except AuthError as exc:
            return {"ok": False, "message": self._redact(f"无法发送验证码：{exc}")}
        except TreeholeError as exc:
            return {"ok": False, "message": self._redact(f"无法发送验证码：{exc}")}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": self._redact(f"网络错误：{exc}")}
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
            return {"ok": False, "message": self._redact(f"验证失败：{exc}")}
        except TreeholeError as exc:
            return {"ok": False, "message": self._redact(f"验证失败：{exc}")}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "message": self._redact(f"网络错误：{exc}")}
        return {"ok": True, "message": "短信验证完成，现在可以读取树洞消息"}


DEFAULT_NOTIFY_INTERVAL = 60
MIN_NOTIFY_INTERVAL = 30

# The macOS notifier daemon runs the vendored treehole CLI under launchd. Since
# the package is now vendored, pku-captain's own venv exposes a `treehole`
# console script (see pyproject [project.scripts]); point launchd at that
# absolute path, falling back to whatever `treehole` is on PATH.
_TREEHOLE_VENV_BIN = _REPO_ROOT / ".venv" / "bin" / "treehole"

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


class TreeholeHistoryStore:
    """Persistent, append-only log of every treehole new reply ever surfaced.

    Distinct from :class:`TreeholeInboxStore`, which clears on read (it drives
    the unread badge): this store *never* clears on read, so the dialog's 历史消息
    tab can show the user's full history of new replies in time order. Records
    are individual comments keyed by ``(pid, cid)`` so re-merging the same poll
    (or an already-accumulated inbox snapshot) is idempotent. Each record keeps
    the comment text/author/timestamp plus the parent hole's text for context.

    ``entries()`` returns records newest-first by comment ``timestamp`` (records
    with no timestamp sink to the bottom). Two deliberate limitations, inherited
    from the upstream poll rather than introduced here: (1) a poll that reports
    only a reply-*count* increase carries no comment text or timestamp, so it
    contributes nothing here — history is therefore "every new reply we could
    date", not literally every detected change; (2) the dashboard polls with a
    per-interval ``limit``, so if more holes update in one interval than that
    limit, the overflow never reaches this store either.

    ``path=None`` keeps it in-memory (the GUI default and tests use this so they
    never touch the repo's ``data/``); ``MainWindow`` injects a real path.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: list[dict[str, Any]] = self._load()
        self._seen: set[tuple[str, str]] = {
            (str(r.get("pid")), str(r.get("cid"))) for r in self._records
        }

    def _load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        records = data.get("records") if isinstance(data, dict) else data
        if not isinstance(records, list):
            return []
        return [r for r in records if isinstance(r, dict) and r.get("cid") is not None]

    def entries(self) -> list[dict[str, Any]]:
        """All recorded comments, newest-first by timestamp (untimed last)."""
        return sorted(
            (dict(r) for r in self._records),
            key=lambda r: int(r.get("timestamp") or 0),
            reverse=True,
        )

    def count(self) -> int:
        return len(self._records)

    def merge(self, updates: list[dict[str, Any]]) -> None:
        """Absorb each update's ``new_comments`` as dated history records.

        Fed from the raw poll ``updates`` at the same point as the inbox, so the
        history grows even though the inbox is cleared on read. Idempotent: a
        ``(pid, cid)`` already seen is skipped.
        """
        added = False
        for update in updates or []:
            if not isinstance(update, dict):
                continue
            pid = str(update.get("pid") or "")
            hole_text = update.get("text")
            for comment in update.get("new_comments") or []:
                if not isinstance(comment, dict) or comment.get("cid") is None:
                    continue
                cid = str(comment["cid"])
                key = (pid, cid)
                if key in self._seen:
                    continue
                self._seen.add(key)
                self._records.append({
                    "pid": pid,
                    "cid": cid,
                    "text": comment.get("text"),
                    "name_tag": comment.get("name_tag"),
                    "timestamp": comment.get("timestamp"),
                    "hole_text": hole_text,
                })
                added = True
        if added:
            self._save()

    def clear(self) -> None:
        if not self._records:
            return
        self._records = []
        self._seen = set()
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"records": self._records}, ensure_ascii=False)
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
        "Search PKU Treehole holes by keyword or fetch one hole with its full "
        "comment history. Use this when the user asks to search treehole content "
        "or inspect a specific treehole pid."
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
                "description": "Keyword for `search`.",
            },
            "pid": {
                "type": "string",
                "description": "Treehole pid for `fetch`.",
            },
            "limit": {
                "type": "integer",
                "description": "Page size / maximum returned search rows. Default: 10.",
                "minimum": 1,
                "maximum": 50,
                "default": 10,
            },
            "all": {
                "type": "boolean",
                "description": "For `search`, paginate all results up to the library cap.",
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
        keyword = str(args.get("keyword") or "").strip()
        if not keyword:
            return ToolResult(success=False, error="`search` requires a non-empty keyword")
        limit = _bounded_int(args.get("limit"), default=10, minimum=1, maximum=50)
        try:
            client = self._build_client(args)
            if bool(args.get("all", False)):
                results = client.search_all(keyword, limit=limit)
            else:
                data = client.search(keyword, limit=limit)
                results = data.get("list") or []
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

        return ToolResult(
            success=True,
            data={
                "status": "ok",
                "action": "search",
                "keyword": keyword,
                "message": f"树洞搜索返回 {len(results)} 条结果",
                "results": [_hole_to_dict(item) for item in results],
            },
        )

    def _fetch(self, args: dict[str, Any]) -> ToolResult:
        pid = str(args.get("pid") or "").strip().lstrip("#")
        if not pid:
            return ToolResult(success=False, error="`fetch` requires a non-empty pid")
        limit = _bounded_int(args.get("limit"), default=50, minimum=1, maximum=100)
        try:
            client = self._build_client(args)
            hole = client.hole(pid)
            comments = client.comments_all(pid, limit=limit)
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

        return ToolResult(
            success=True,
            data={
                "status": "ok",
                "action": "fetch",
                "pid": pid,
                "message": f"树洞 #{pid} 返回 {len(comments)} 条评论",
                "hole": _hole_to_dict(hole),
                "comments": [_hole_to_dict(item) for item in comments],
                "comment_count": len(comments),
            },
        )

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


def _hole_to_dict(item: object) -> dict[str, Any]:
    return dict(item) if isinstance(item, dict) else {}


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
