"""Credential redaction at the tool boundary.

Proves that secret values we inject/hold never survive into a tool error
string — the path that would otherwise carry them into the conversation, the
LLM request, and data/sessions/*.json.
"""

from __future__ import annotations

import subprocess

import src.tools.treehole_updates as th
from src.tools.plib_materials import run_plib
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


# --- plib wrapper integration ---------------------------------------------

def _patch_plib(monkeypatch, returncode: int, stdout: str, stderr: str) -> None:
    monkeypatch.setattr(
        "src.tools.plib_materials.resolve_executable", lambda _exe: "/bin/plib"
    )

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("src.tools.plib_materials.subprocess.run", fake_run)


def test_run_plib_redacts_injected_credentials_from_stderr(monkeypatch) -> None:
    password = "Sup3rSecret!"
    email = "alice@pku.edu.cn"
    _patch_plib(
        monkeypatch,
        returncode=1,
        stdout="",
        stderr=f"login failed for {email} with password {password}",
    )

    result = run_plib(
        ["login"], env={"PLIB_EMAIL": email, "PLIB_PASSWORD": password}
    )

    assert result["ok"] is False
    assert password not in result["error"]
    assert email not in result["error"]
    assert REDACTED in result["error"]


def test_run_plib_redacts_on_invalid_json(monkeypatch) -> None:
    password = "Sup3rSecret!"
    _patch_plib(
        monkeypatch,
        returncode=1,
        stdout=f"panic: bad config, password={password}",
        stderr="",
    )

    result = run_plib(["quota"], env={"PLIB_PASSWORD": password})

    assert result["ok"] is False
    assert password not in result["error"]


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
