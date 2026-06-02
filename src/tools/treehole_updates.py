"""PKU Treehole update monitor tool.

This tool wraps the local ``pku-treehole-cli`` library and exposes one
conservative operation for the agent/GUI: check whether watched or followed
holes gained replies since the last baseline.
"""

from __future__ import annotations

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
