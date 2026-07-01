"""Credential redaction at the tool boundary.

Proves that secret values we inject/hold never survive into a tool error
string — the path that would otherwise carry them into the conversation, the
LLM request, and data/sessions/*.json.
"""

from __future__ import annotations

from pathlib import Path

from plib_cli.errors import AuthError

import src.tools.treehole_updates as th
from src.tools.plib_materials import PLibMaterialsTool
from src.tools.redact import REDACTED, redact

# --- the pure helper -------------------------------------------------------

def test_redact_replaces_each_occurrence() -> None:
    assert redact("a SECRET b SECRET", ["SECRET"]) == f"a {REDACTED} b {REDACTED}"


def test_redact_handles_multiple_secrets() -> None:
    out = redact("user alice pass hunter2", ["alice", "hunter2"])
    assert "alice" not in out and "hunter2" not in out


def test_redact_skips_empty_or_whitespace_secret() -> None:
    # An empty secret must NOT shred the text (str.replace("", x) inserts x
    # between every char); whitespace-only is likewise ignored.
    assert redact("untouched", ["", "  "]) == "untouched"


def test_redact_noops_on_empty_text() -> None:
    assert redact("", ["secret"]) == ""


def test_redact_custom_placeholder() -> None:
    assert redact("x secret y", ["secret"], placeholder="#") == "x # y"


# --- plib tool integration -------------------------------------------------
#
# The tool holds credentials (stored secrets, or passed for `login`) and calls
# the vendored library in-process; a PlibError message that echoes a credential
# must be redacted before it reaches the ToolResult.


def _write_plib_secrets(dir_: Path, email: str, password: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "email").write_text(email, encoding="utf-8")
    (dir_ / "password").write_text(password, encoding="utf-8")


def test_plib_redacts_stored_credentials_from_error(tmp_path) -> None:
    password = "Sup3rSecret!"
    email = "alice@pku.edu.cn"
    secrets = tmp_path / "plib"
    _write_plib_secrets(secrets, email, password)

    def factory(timeout, credentials):  # noqa: ANN001
        raise AuthError(f"login failed for {email} with password {password}")

    tool = PLibMaterialsTool(client_factory=factory, secrets_dir=secrets)
    result = tool.invoke({"action": "quota"})

    assert result.success is False
    assert password not in str(result.error)
    assert email not in str(result.error)
    assert REDACTED in str(result.error)


def test_plib_redacts_login_credentials_from_error(tmp_path) -> None:
    password = "Hunter2!"
    email = "bob@pku.edu.cn"

    def factory(timeout, credentials):  # noqa: ANN001
        raise AuthError(f"rejected {email} / {password}")

    # No stored secrets — the redacted values come from the login args.
    tool = PLibMaterialsTool(client_factory=factory, secrets_dir=tmp_path / "plib")
    result = tool.invoke({"action": "login", "email": email, "password": password})

    assert result.success is False
    assert password not in str(result.error)
    assert email not in str(result.error)
    assert REDACTED in str(result.error)


# --- treehole auth-service integration ------------------------------------

def test_treehole_login_redacts_credentials_in_auth_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(th, "Credentials", lambda **kw: kw)

    class _Store:
        def __init__(self, path) -> None:  # noqa: ANN001
            self.path = path

        def load_or_none(self):
            return None

        def save(self, identity) -> None:  # noqa: ANN001
            pass

    monkeypatch.setattr(th, "SessionStore", _Store)

    def _login(_creds, **_kw):  # noqa: ANN003
        raise th.AuthError("rejected password=Hunter2! for uid 2500013225")

    monkeypatch.setattr(th, "login", _login)

    svc = th.TreeholeAuthService(secrets_dir=tmp_path)
    res = svc.login("2500013225", "Hunter2!")

    assert res["ok"] is False
    assert "Hunter2!" not in res["message"]
    assert "2500013225" not in res["message"]
    assert REDACTED in res["message"]
