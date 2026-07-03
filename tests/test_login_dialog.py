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


def test_treehole_tab_disabled_offline(app: QApplication, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    dialog = LoginDialog(store=store, auth=None, plib_tool=None, offline=True)
    assert not dialog._th_uid.isEnabled()
    assert not dialog._th_password.isEnabled()
    for button in dialog._th_buttons:
        assert not button.isEnabled()


def test_treehole_login_persists_via_auth_service(app: QApplication, tmp_path) -> None:
    # Online: the treehole tab drives the injected auth service; a successful
    # login emits the treehole refresh key.
    store = CredentialStore(tmp_path / "secrets")

    class FakeAuth:
        def status(self) -> dict[str, object]:
            return {"ok": False, "message": "尚未登录"}

        def login(self, uid: str, password: str) -> dict[str, object]:
            return {"ok": True, "message": "登录成功，请完成短信验证"}

        def send_sms(self) -> dict[str, object]:
            return {"ok": True, "message": "验证码已发送"}

        def verify_sms(self, code: str) -> dict[str, object]:
            return {"ok": True, "message": "验证完成"}

    dialog = LoginDialog(store=store, auth=FakeAuth(), plib_tool=None, offline=False)
    emitted: list[list[str]] = []
    dialog.credentials_changed.connect(emitted.append)

    dialog._th_uid.setText("2500013225")
    dialog._th_password.setText("pw")
    dialog._treehole_login()
    _drain()
    dialog.accept()

    assert emitted == [["treehole_updates"]]
