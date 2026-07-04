"""LoginDialog — the one universal account / login page.

Consolidates what used to be three scattered entry points (treehole IAAA+SMS
buried in the messages dialog, a P-Lib dialog that never persisted, and no
API-key entry at all) into a single tabbed dialog opened from the dashboard's
『设置』button:

* **统一身份 · 树洞** — IAAA ``学号``+密码 login then SMS verify, via the existing
  ``TreeholeAuthService`` (writes ``secrets/treehole/{id,password}`` + caches
  ``session.json``). On success it also mirrors the same IAAA identity into
  ``secrets/pku/{id,password}`` (via ``CredentialStore.save_pku``) so one login
  provisions the pku3b tools too. Needs online mode (it hits the network).
* **P-Lib** — email+password, now *persisted* through ``CredentialStore`` (the
  old dialog only validated), so login survives a restart. Optionally validated
  live when the plib tool is registered (online).
* **模型配置** — the chat brains as two configurable roles, 文本模型 / 视觉模型.
  Each carries an API key + endpoint + model name; DeepSeek/Kimi are only the
  defaults. Fully usable offline (writes ``secrets/models.json``); changes take
  effect on the next launch.
* **网络代理** — the process-wide proxy mode (跟随系统 / 直连 / 自定义 URL, see
  ``src.core.network``). Pure local config (writes ``secrets/network.json``),
  applied immediately via ``apply_proxy`` — no restart needed.

All persistence goes through ``CredentialStore`` and ``TreeholeAuthService`` —
the dialog constructs no ``Tool`` / ``LLMProvider`` subclasses itself
(integration contract §1). Blocking calls (login, SMS, plib validation) run off
the UI thread via ``run_async``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.credentials import CredentialStore, model_default
from ..core.network import (
    DEFAULT_PROXY_URL,
    ProxyConfig,
    apply_proxy,
    normalize_proxy_url,
)
from ..tools.base import Tool
from .tool_call_worker import run_async

# Tool keys a login change should trigger a dashboard refresh for; "models" is a
# sentinel the window turns into a "restart to apply" hint rather than a card,
# and "network" is a sentinel for a proxy change (re-poll every network card).
_TREEHOLE_KEY = "treehole_updates"
_PLIB_KEY = "plib_materials"
_MODELS_KEY = "models"
_NETWORK_KEY = "network"
# The pku3b cards a treehole login (which mirrors the shared IAAA identity into
# secrets/pku/) newly provisions — refresh them once creds land.
_PKU_KEYS = ("pku3b_assignments", "pku3b_announcements")

# The two model roles the 模型配置 tab exposes, in display order.
_MODEL_ROLE_LABELS = (("text", "文本模型"), ("visual", "视觉模型"))


class _ModelRoleForm(QGroupBox):
    """One role's editable API key / endpoint / model, prefilled from the store."""

    # 上下文长度 input units: display label -> raw-token multiplier.
    _WINDOW_UNITS = (("令牌", 1), ("千 (k)", 1_000), ("百万 (m)", 1_000_000))

    def __init__(self, role: str, label: str, store: CredentialStore) -> None:
        super().__init__(label)
        self._role = role
        cfg = store.model(role)

        self._key_input = QLineEdit(cfg.api_key)
        self._key_input.setObjectName("TreeholeAuthInput")
        self._key_input.setPlaceholderText("API 密钥")
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._base_input = QLineEdit(cfg.base_url)
        self._base_input.setObjectName("TreeholeAuthInput")
        self._base_input.setPlaceholderText(model_default(role, "base_url"))
        self._model_input = QLineEdit(cfg.model)
        self._model_input.setObjectName("TreeholeAuthInput")
        self._model_input.setPlaceholderText(model_default(role, "model"))
        window_text, window_unit_index = self._display_window(cfg.context_window)
        self._window_input = QLineEdit(window_text)
        self._window_input.setObjectName("TreeholeAuthInput")
        self._window_input.setPlaceholderText("留空使用默认")
        # Unit multiplier for the raw token count (令牌 ×1 / 千 ×1k / 百万 ×1M).
        # Storage stays raw tokens; the unit is input/display sugar only.
        self._window_unit = QComboBox()
        for label_text, factor in self._WINDOW_UNITS:
            self._window_unit.addItem(label_text, factor)
        self._window_unit.setCurrentIndex(window_unit_index)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("API 密钥"), 0, 0)
        form.addWidget(self._key_input, 0, 1)
        form.addWidget(QLabel("接口地址"), 1, 0)
        form.addWidget(self._base_input, 1, 1)
        form.addWidget(QLabel("模型名称"), 2, 0)
        form.addWidget(self._model_input, 2, 1)
        form.addWidget(QLabel("上下文长度"), 3, 0)
        window_row = QHBoxLayout()
        window_row.setContentsMargins(0, 0, 0, 0)
        window_row.setSpacing(6)
        window_row.addWidget(self._window_input, 1)
        window_row.addWidget(self._window_unit)
        form.addLayout(window_row, 3, 1)
        form.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(form)

    @property
    def role(self) -> str:
        return self._role

    def values(self) -> dict[str, object]:
        return {
            "api_key": self._key_input.text(),
            "base_url": self._base_input.text(),
            "model": self._model_input.text(),
            "context_window": self._parsed_window(),
        }

    def _parsed_window(self) -> int | None:
        """The 上下文长度 field as a positive raw-token count, or None.

        Multiplies the entered number by the selected unit (令牌 ×1 / 千 ×1 000
        / 百万 ×1 000 000); blank / non-numeric / <=0 -> None ("use default").
        """
        text = self._window_input.text().strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            return None
        if value <= 0:
            return None
        tokens = value * int(self._window_unit.currentData())
        return tokens if tokens > 0 else None

    @staticmethod
    def _display_window(tokens: int | None) -> tuple[str, int]:
        """Split a stored token count into (line-edit text, unit combo index).

        Picks the largest exact unit so a load->save round-trip is stable:
        exact multiple of 1 000 000 -> 百万, of 1 000 -> 千, else 令牌. Blank
        (None) shows an empty field on the 令牌 unit.
        """
        if tokens is None or tokens <= 0:
            return "", 0
        if tokens % 1_000_000 == 0:
            return str(tokens // 1_000_000), 2
        if tokens % 1_000 == 0:
            return str(tokens // 1_000), 1
        return str(tokens), 0

    def has_key(self) -> bool:
        return bool(self._key_input.text().strip())


class LoginDialog(QDialog):
    """Universal account / login page. Emits `credentials_changed` with the tool
    keys (and the `models` sentinel) whose backing credentials were updated."""

    credentials_changed = pyqtSignal(list)

    def __init__(
        self,
        *,
        store: CredentialStore | None = None,
        auth: Any | None = None,
        plib_tool: Tool | None = None,
        offline: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(600, 480)
        self._store = store or CredentialStore()
        self._auth = auth
        self._plib_tool = plib_tool
        self._offline = offline
        # Retain every in-flight async handle: a second run_async must not let
        # the first's signals object be GC'd while its pooled task is queued
        # (that races into "wrapped C/C++ object deleted"). Cleared when the
        # dialog is destroyed, by which point its tasks have run.
        self._pending: list[object] = []
        self._changed: set[str] = set()
        # (uid, password) of an in-flight treehole *login*, mirrored into
        # secrets/pku/ only once IAAA accepts it (so a wrong password is never
        # persisted for pku3b). Set by `_treehole_login`, consumed on success.
        self._pending_iaaa: tuple[str, str] | None = None

        title = QLabel("设置")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "在这里集中管理北大统一身份（树洞）、P-Lib 图书账号、对话模型与网络代理。"
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        tabs = QTabWidget()
        tabs.addTab(self._build_treehole_tab(), "统一身份 · 树洞")
        tabs.addTab(self._build_plib_tab(), "P-Lib 图书")
        tabs.addTab(self._build_models_tab(), "模型配置")
        tabs.addTab(self._build_network_tab(), "网络代理")

        close_button = QPushButton("关闭")
        close_button.setObjectName("InlineToggleButton")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(tabs, 1)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        if self._auth is not None and not self._offline:
            self._refresh_treehole_status()
        self._refresh_plib_status()

    # -- treehole tab -----------------------------------------------------
    def _build_treehole_tab(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("TreeholeAuthPanel")

        self._th_status = QLabel("正在检查登录状态...")
        self._th_status.setObjectName("TreeholeAuthStatus")
        self._th_status.setWordWrap(True)

        self._th_uid = QLineEdit()
        self._th_uid.setObjectName("TreeholeAuthInput")
        self._th_uid.setPlaceholderText("北大账号 / 学号")
        self._th_password = QLineEdit()
        self._th_password.setObjectName("TreeholeAuthInput")
        self._th_password.setPlaceholderText("密码")
        self._th_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._th_sms = QLineEdit()
        self._th_sms.setObjectName("TreeholeAuthInput")
        self._th_sms.setPlaceholderText("短信验证码")

        login_button = QPushButton("登录")
        login_button.setObjectName("SecondaryButton")
        login_button.clicked.connect(self._treehole_login)
        send_button = QPushButton("发送验证码")
        send_button.setObjectName("SecondaryButton")
        send_button.clicked.connect(self._treehole_send_sms)
        verify_button = QPushButton("完成验证")
        verify_button.setObjectName("PrimaryButton")
        verify_button.clicked.connect(self._treehole_verify_sms)
        logout_button = QPushButton("退出登录")
        logout_button.setObjectName("InlineToggleButton")
        logout_button.clicked.connect(self._treehole_logout)
        self._th_buttons = [login_button, send_button, verify_button, logout_button]

        account_label = QLabel("1 账号登录")
        account_label.setObjectName("TreeholeAuthStep")
        sms_label = QLabel("2 短信验证")
        sms_label.setObjectName("TreeholeAuthStep")

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(account_label, 0, 0, 1, 3)
        form.addWidget(self._th_uid, 1, 0)
        form.addWidget(self._th_password, 1, 1)
        form.addWidget(login_button, 1, 2)
        form.addWidget(sms_label, 2, 0, 1, 3)
        form.addWidget(self._th_sms, 3, 0)
        form.addWidget(send_button, 3, 1)
        form.addWidget(verify_button, 3, 2)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._th_status)
        layout.addLayout(form)
        layout.addWidget(logout_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)

        if self._offline or self._auth is None:
            for widget in (self._th_uid, self._th_password, self._th_sms, *self._th_buttons):
                widget.setEnabled(False)
            self._set_status(
                self._th_status, "树洞登录需要在线模式启动（python -m src --online）。", "error"
            )
        return panel

    def _refresh_treehole_status(self) -> None:
        self._set_status(self._th_status, "正在检查登录状态...", "pending")
        self._pending.append(
            run_async(
                self._auth.status,
                on_done=self._on_treehole_status,
                on_error=self._on_treehole_status_error,
            )
        )

    def _on_treehole_status(self, result: object) -> None:
        data = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        if data.get("ok"):
            name = data.get("name") or "未知用户"
            self._set_status(self._th_status, f"已登录 · {name}", "ok")
        else:
            self._set_status(self._th_status, str(data.get("message") or "尚未登录树洞"), "error")

    def _on_treehole_status_error(self, message: str) -> None:
        self._set_status(self._th_status, f"无法检查登录状态：{message}", "error")

    def _treehole_login(self) -> None:
        uid, password = self._th_uid.text(), self._th_password.text()
        # Remember the identity so it can be mirrored into secrets/pku/ if the
        # login succeeds (same IAAA account the pku3b tools need).
        self._pending_iaaa = (uid, password)
        self._run_treehole(lambda: self._auth.login(uid, password))

    def _treehole_send_sms(self) -> None:
        self._run_treehole(self._auth.send_sms)

    def _treehole_verify_sms(self) -> None:
        self._run_treehole(lambda: self._auth.verify_sms(self._th_sms.text()))

    def _treehole_logout(self) -> None:
        # 统一身份 covers both treehole and pku3b, so logging out drops the
        # mirrored pku creds + cookie jar as well.
        self._store.clear_treehole()
        self._store.clear_pku()
        self._pending_iaaa = None
        self._set_status(self._th_status, "已退出统一身份登录。", "error")
        self._mark_changed(_TREEHOLE_KEY)
        for key in _PKU_KEYS:
            self._mark_changed(key)

    def _run_treehole(self, action: Callable[[], dict[str, object]]) -> None:
        self._set_treehole_busy(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending.append(
            run_async(
                action,
                on_done=self._on_treehole_action,
                on_error=self._on_treehole_error,
            )
        )

    def _on_treehole_action(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._set_treehole_busy(False)
        data = result if isinstance(result, dict) else {"ok": False, "message": str(result)}
        if data.get("ok"):
            self._set_status(self._th_status, str(data.get("message") or "操作完成"), "ok")
            self._mark_changed(_TREEHOLE_KEY)
            self._mirror_iaaa_to_pku()
            self._refresh_treehole_status()
        else:
            self._pending_iaaa = None
            message = str(data.get("message") or "操作失败")
            self._set_status(self._th_status, message, "error")
            QMessageBox.warning(self, "树洞登录", message)

    def _on_treehole_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._set_treehole_busy(False)
        self._pending_iaaa = None
        self._set_status(self._th_status, message, "error")
        QMessageBox.warning(self, "树洞登录", message)

    def _mirror_iaaa_to_pku(self) -> None:
        """After a successful treehole login, provision the pku3b tools too.

        Treehole and pku3b share one IAAA identity, so a single 统一身份 login
        writes secrets/pku/{id,password} as well — no separate hand-placed file.
        Only fires for a login (send/verify-SMS leave `_pending_iaaa` unset).
        """
        pending, self._pending_iaaa = self._pending_iaaa, None
        if pending is None:
            return
        uid, password = pending
        if not uid.strip() or not password:
            return
        self._store.save_pku(uid, password)
        for key in _PKU_KEYS:
            self._mark_changed(key)

    def _set_treehole_busy(self, busy: bool) -> None:
        for button in self._th_buttons:
            button.setEnabled(not busy)

    # -- P-Lib tab --------------------------------------------------------
    def _build_plib_tab(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PLibAuthPanel")

        self._plib_status = QLabel("请输入 P-Lib 邮箱和密码")
        self._plib_status.setObjectName("PLibAuthStatus")
        self._plib_status.setWordWrap(True)

        stored = self._store.plib()
        self._plib_email = QLineEdit(stored[0] if stored else "")
        self._plib_email.setObjectName("TreeholeAuthInput")
        self._plib_email.setPlaceholderText("邮箱")
        self._plib_password = QLineEdit(stored[1] if stored else "")
        self._plib_password.setObjectName("TreeholeAuthInput")
        self._plib_password.setPlaceholderText("密码")
        self._plib_password.setEchoMode(QLineEdit.EchoMode.Password)

        self._plib_save = QPushButton("保存并登录")
        self._plib_save.setObjectName("PrimaryButton")
        self._plib_save.clicked.connect(self._plib_save_login)
        self._plib_password.returnPressed.connect(self._plib_save_login)
        plib_clear = QPushButton("清除凭据")
        plib_clear.setObjectName("InlineToggleButton")
        plib_clear.clicked.connect(self._plib_clear)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(QLabel("邮箱"), 0, 0)
        form.addWidget(self._plib_email, 0, 1)
        form.addWidget(QLabel("密码"), 1, 0)
        form.addWidget(self._plib_password, 1, 1)
        form.setColumnStretch(1, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self._plib_save)
        buttons.addStretch(1)
        buttons.addWidget(plib_clear)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._plib_status)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return panel

    def _refresh_plib_status(self) -> None:
        if self._store.has_plib():
            self._set_status(self._plib_status, "已保存 P-Lib 凭据。", "ok")
        else:
            self._set_status(self._plib_status, "尚未配置 P-Lib 账号。", "error")

    def _plib_save_login(self) -> None:
        email = self._plib_email.text().strip()
        password = self._plib_password.text()
        if not email or not password:
            QMessageBox.warning(self, "P-Lib", "请输入邮箱和密码。")
            return
        # Persist first (works offline, survives restart), then validate live if
        # the tool is registered.
        self._store.save_plib(email, password)
        self._mark_changed(_PLIB_KEY)
        if self._plib_tool is None:
            self._set_status(self._plib_status, "已保存，将在在线模式下生效。", "ok")
            return
        self._plib_save.setEnabled(False)
        self._set_status(self._plib_status, "正在登录 P-Lib...", "pending")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._pending.append(
            run_async(
                lambda: self._plib_tool.invoke(
                    {"action": "login", "email": email, "password": password}
                ),
                on_done=self._on_plib_login,
                on_error=self._on_plib_error,
            )
        )

    def _on_plib_login(self, result: object) -> None:
        QApplication.restoreOverrideCursor()
        self._plib_save.setEnabled(True)
        if not getattr(result, "success", False):
            error = str(getattr(result, "error", "") or "登录失败")
            self._set_status(self._plib_status, f"凭据已保存，但登录校验失败：{error}", "error")
            return
        data = getattr(result, "data", {})
        remaining = data.get("quota_remaining") if isinstance(data, dict) else None
        message = "登录成功并已保存凭据"
        if remaining is not None:
            message += f" · 今日剩余下载：{remaining}"
        self._set_status(self._plib_status, message, "ok")

    def _on_plib_error(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self._plib_save.setEnabled(True)
        self._set_status(self._plib_status, f"凭据已保存，但登录校验失败：{message}", "error")

    def _plib_clear(self) -> None:
        self._store.clear_plib()
        self._plib_email.clear()
        self._plib_password.clear()
        self._mark_changed(_PLIB_KEY)
        self._set_status(self._plib_status, "已清除 P-Lib 凭据。", "error")

    # -- models tab -------------------------------------------------------
    def _build_models_tab(self) -> QWidget:
        panel = QWidget()
        self._model_forms = [
            _ModelRoleForm(role, label, self._store)
            for role, label in _MODEL_ROLE_LABELS
        ]

        hint = QLabel(
            "DeepSeek / Kimi 为默认，可改为任意 OpenAI 兼容端点，保存后即时生效。"
            "上下文长度留空则使用模型默认值。"
        )
        hint.setObjectName("DialogSubtitle")
        hint.setWordWrap(True)
        self._model_status = QLabel("")
        self._model_status.setObjectName("PLibAuthStatus")
        self._model_status.setWordWrap(True)

        save_button = QPushButton("保存模型配置")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_models)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(hint)
        for form in self._model_forms:
            layout.addWidget(form)
        layout.addWidget(self._model_status)
        layout.addWidget(save_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)
        return panel

    def _save_models(self) -> None:
        for form in self._model_forms:
            values = form.values()
            window = values["context_window"]
            self._store.save_model(
                form.role,
                api_key=str(values["api_key"]),
                base_url=str(values["base_url"]),
                model=str(values["model"]),
                context_window=window if isinstance(window, int) else None,
            )
        self._mark_changed(_MODELS_KEY)
        self._set_status(self._model_status, "已保存模型配置并即时生效。", "ok")

    # -- network proxy tab --------------------------------------------------
    def _build_network_tab(self) -> QWidget:
        panel = QWidget()
        cfg = self._store.proxy()

        hint = QLabel(
            "代理作用于全部网络访问（教学网 / 树洞 / P-Lib / 教务 / 模型接口），"
            "保存后立即生效。校外通过 Clash / mihomo 等访问校内资源时，"
            "选择「自定义代理」并填写本机代理地址。"
        )
        hint.setObjectName("DialogSubtitle")
        hint.setWordWrap(True)

        self._proxy_system = QRadioButton("跟随系统代理（默认）")
        self._proxy_direct = QRadioButton("直连（忽略系统代理）")
        self._proxy_manual = QRadioButton("自定义代理")
        self._proxy_url = QLineEdit(cfg.url)
        self._proxy_url.setObjectName("TreeholeAuthInput")
        self._proxy_url.setPlaceholderText(DEFAULT_PROXY_URL)
        {
            "direct": self._proxy_direct,
            "manual": self._proxy_manual,
        }.get(cfg.mode, self._proxy_system).setChecked(True)
        # The URL only matters in manual mode; grey it out elsewhere.
        self._proxy_url.setEnabled(cfg.mode == "manual")
        for radio in (self._proxy_system, self._proxy_direct, self._proxy_manual):
            radio.toggled.connect(
                lambda _checked: self._proxy_url.setEnabled(
                    self._proxy_manual.isChecked()
                )
            )

        self._network_status = QLabel("")
        self._network_status.setObjectName("PLibAuthStatus")
        self._network_status.setWordWrap(True)

        save_button = QPushButton("保存代理设置")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_network)

        url_row = QHBoxLayout()
        url_row.setContentsMargins(24, 0, 0, 0)
        url_row.addWidget(QLabel("代理地址"))
        url_row.addWidget(self._proxy_url, 1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(hint)
        layout.addWidget(self._proxy_system)
        layout.addWidget(self._proxy_direct)
        layout.addWidget(self._proxy_manual)
        layout.addLayout(url_row)
        layout.addWidget(self._network_status)
        layout.addWidget(save_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch(1)
        return panel

    def _save_network(self) -> None:
        if self._proxy_manual.isChecked():
            mode = "manual"
        elif self._proxy_direct.isChecked():
            mode = "direct"
        else:
            mode = "system"
        url = normalize_proxy_url(self._proxy_url.text())
        if mode == "manual":
            if not url:
                QMessageBox.warning(
                    self, "网络代理", f"请输入代理地址，例如 {DEFAULT_PROXY_URL}。"
                )
                return
            self._proxy_url.setText(url)
        # Keep the URL even in system/direct mode so switching back to 自定义
        # remembers the last address; apply_proxy only reads it in manual mode.
        config = ProxyConfig(mode=mode, url=url)
        self._store.save_proxy(config)
        apply_proxy(config)
        self._mark_changed(_NETWORK_KEY)
        self._set_status(self._network_status, "已保存代理设置，立即生效。", "ok")

    # -- shared -----------------------------------------------------------
    def _mark_changed(self, key: str) -> None:
        self._changed.add(key)

    @staticmethod
    def _set_status(label: QLabel, text: str, state: str) -> None:
        label.setText(text)
        label.setProperty("authState", state)
        style = label.style()
        style.unpolish(label)
        style.polish(label)

    def accept(self) -> None:  # noqa: D401 - Qt override
        if self._changed:
            self.credentials_changed.emit(sorted(self._changed))
        super().accept()

    def reject(self) -> None:  # noqa: D401 - Qt override
        if self._changed:
            self.credentials_changed.emit(sorted(self._changed))
        super().reject()
