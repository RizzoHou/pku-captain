"""LoginDialog — the universal account center.

Headless/offscreen, hermetic (tmp secrets, no network). Covers: models tab
persists both roles + emits the `models` sentinel; the P-Lib tab persists
credentials and validates through an injected tool; the treehole tab is
disabled offline; `credentials_changed` carries exactly the touched areas.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.credentials import CredentialStore  # noqa: E402
from src.tools.base import Tool, ToolResult  # noqa: E402
from src.ui import login_dialog  # noqa: E402
from src.ui.login_dialog import LoginDialog  # noqa: E402


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _drain() -> None:
    QThreadPool.globalInstance().waitForDone(3000)
    QApplication.processEvents()
    QApplication.processEvents()


class FakePlibTool(Tool):
    name = "plib_materials"
    description = "fake"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(args)
        return ToolResult(success=True, data={"quota_remaining": 5})


def test_models_tab_persists_both_roles_and_emits(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._model_forms[0]._key_input.setText("text-key")
    dialog._model_forms[0]._base_input.setText("https://proxy.example.com/v1")
    dialog._model_forms[0]._model_input.setText("custom")
    dialog._model_forms[1]._key_input.setText("visual-key")
    dialog._save_models()
    dialog.accept()

    text = store.model("text")
    assert text.api_key == "text-key"
    assert text.base_url == "https://proxy.example.com/v1"
    assert text.model == "custom"
    assert store.model("visual").api_key == "visual-key"
    assert emitted == [["models"]]


def test_models_tab_context_window_unit_multiplies(app: QApplication, tmp_path) -> None:
    # The 上下文长度 unit combo is input sugar: "256" on the 千 (k) unit persists
    # a raw 256_000 token count. Storage stays token-based end to end.
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)

    form = dialog._model_forms[0]  # text role
    form._key_input.setText("text-key")
    form._window_input.setText("256")
    form._window_unit.setCurrentIndex(1)  # 千 (k)
    dialog._save_models()

    assert store.model("text").context_window == 256_000


def test_models_tab_context_window_prefills_largest_unit(
    app: QApplication, tmp_path
) -> None:
    # A stored 1_000_000 tokens round-trips as value=1 on the 百万 (m) unit, so
    # a load->save cycle is stable rather than drifting to a bigger raw number.
    store = CredentialStore(tmp_path / "secrets")
    store.save_model("text", api_key="k", base_url="", model="", context_window=1_000_000)
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)

    form = dialog._model_forms[0]
    assert form._window_input.text() == "1"
    assert form._window_unit.currentData() == 1_000_000  # 百万 (m)
    assert form._parsed_window() == 1_000_000


def test_plib_tab_persists_and_validates(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    tool = FakePlibTool()
    dialog = LoginDialog(store=store, auth=None, plib_tool=tool, offline=False)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._plib_email.setText("user@pku.edu.cn")
    dialog._plib_password.setText("pw")
    dialog._plib_save_login()
    _drain()

    # Persisted immediately (survives restart) and validated via the tool.
    assert store.plib() == ("user@pku.edu.cn", "pw")
    assert tool.calls == [
        {"action": "login", "email": "user@pku.edu.cn", "password": "pw"}
    ]
    dialog.accept()
    assert emitted == [["plib_materials"]]


def test_plib_tab_saves_without_tool_offline(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    dialog._plib_email.setText("a@b.c")
    dialog._plib_password.setText("pw")
    dialog._plib_save_login()  # no tool → save only, no validation, no crash
    assert store.plib() == ("a@b.c", "pw")


def test_agent_tab_persists_tool_rounds_and_emits(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._tool_rounds_spin.setValue(12)
    dialog._save_tool_rounds()
    dialog.accept()

    assert store.tool_rounds() == 12
    assert emitted == [["tool_rounds"]]


def test_agent_tab_prefills_tool_rounds_from_store(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_tool_rounds(20)
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    assert dialog._tool_rounds_spin.value() == 20


def test_settings_tabs_use_pkuhub_not_plib(app: QApplication, tmp_path) -> None:
    # The materials tab is rebranded PKUHub; no user-visible "P-Lib 图书" tab
    # remains, and the 对话设置 tab exists.
    from PyQt6.QtWidgets import QTabWidget

    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    tabs = dialog.findChild(QTabWidget)
    titles = [tabs.tabText(i) for i in range(tabs.count())]
    assert "PKUHub" in titles
    assert "对话设置" in titles
    assert not any("P-Lib" in t for t in titles)


def test_treehole_tab_disabled_offline(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    assert not dialog._th_uid.isEnabled()
    assert not dialog._th_password.isEnabled()
    for button in dialog._th_buttons:
        assert not button.isEnabled()


class _FakeAuth:
    """Stand-in treehole auth service that reports each action as succeeding."""

    def __init__(self, *, login_ok: bool = True) -> None:
        self._login_ok = login_ok

    def status(self) -> dict[str, object]:
        return {"ok": False, "message": "尚未登录"}

    def login(self, uid: str, password: str) -> dict[str, object]:
        if self._login_ok:
            return {"ok": True, "message": "登录成功，请完成短信验证"}
        return {"ok": False, "message": "账号或密码错误"}

    def send_sms(self) -> dict[str, object]:
        return {"ok": True, "message": "验证码已发送"}

    def verify_sms(self, code: str) -> dict[str, object]:
        return {"ok": True, "message": "验证完成"}


def test_treehole_login_persists_and_mirrors_pku(app: QApplication, tmp_path) -> None:
    # Online: a successful 统一身份 login mirrors the same IAAA identity into
    # secrets/pku/ and refreshes the treehole + pku3b cards.
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=_FakeAuth(), plib_tool=None, offline=False)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._th_uid.setText("2500013225")
    dialog._th_password.setText("pw")
    dialog._treehole_login()
    _drain()
    dialog.accept()

    assert store.pku() == ("2500013225", "pw")
    assert emitted == [
        ["pku3b_announcements", "pku3b_assignments", "treehole_updates"]
    ]


def test_treehole_login_failure_does_not_mirror_pku(
    app: QApplication, tmp_path, monkeypatch
) -> None:
    # A rejected IAAA login must not persist pku creds (avoid a wrong password
    # silently breaking the pku3b tools). Stub the modal warning so the headless
    # error path doesn't block.
    monkeypatch.setattr(login_dialog.QMessageBox, "warning", lambda *a, **k: None)
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=_FakeAuth(login_ok=False), plib_tool=None, offline=False)

    dialog._th_uid.setText("2500013225")
    dialog._th_password.setText("wrong")
    dialog._treehole_login()
    _drain()

    assert store.pku() is None


def test_treehole_logout_clears_pku(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_pku("2500013225", "pw")
    dialog = LoginDialog(store=store, auth=_FakeAuth(), plib_tool=None, offline=False)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._treehole_logout()
    dialog.accept()

    assert store.pku() is None
    assert emitted == [
        ["pku3b_announcements", "pku3b_assignments", "treehole_updates"]
    ]


@pytest.fixture
def proxy_env(monkeypatch):
    """Snapshot/restore the managed proxy env vars around a network-tab test."""
    from src.core import network

    saved = {name: os.environ.get(name) for name in network._MANAGED_VARS}
    for name in network._MANAGED_VARS:
        os.environ.pop(name, None)
    monkeypatch.setattr(network, "_original_env", None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_network_tab_persists_applies_and_emits(
    app: QApplication, tmp_path, proxy_env
) -> None:
    from src.core.network import ProxyConfig

    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._proxy_manual.setChecked(True)
    dialog._proxy_url.setText("127.0.0.1:7890")  # scheme-less on purpose
    dialog._save_network()
    dialog.accept()

    assert store.proxy() == ProxyConfig(mode="manual", url="http://127.0.0.1:7890")
    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"
    assert emitted == [["network"]]


def test_network_tab_prefills_and_gates_url(app: QApplication, tmp_path, proxy_env) -> None:
    from src.core.network import ProxyConfig

    store = CredentialStore(tmp_path / "secrets")
    store.save_proxy(ProxyConfig(mode="manual", url="http://127.0.0.1:7890"))
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)

    assert dialog._proxy_manual.isChecked()
    assert dialog._proxy_url.text() == "http://127.0.0.1:7890"
    assert dialog._proxy_url.isEnabled()

    dialog._proxy_direct.setChecked(True)
    assert not dialog._proxy_url.isEnabled()

    dialog._save_network()
    # Direct mode keeps the remembered URL for a later switch back to manual.
    assert store.proxy() == ProxyConfig(mode="direct", url="http://127.0.0.1:7890")
    assert "https_proxy" not in os.environ
    assert os.environ["NO_PROXY"] == "*"
