"""Tests for credential resolution (no network).

The daily download quota is no longer tracked locally — it's read from the
server's /profile page, so its parser is covered in ``test_parsers.py``.
"""

from __future__ import annotations

from plib_cli.config import Credentials, load_credentials


def test_credentials_from_env(monkeypatch) -> None:
    monkeypatch.setenv("PLIB_EMAIL", "a@b.com")
    monkeypatch.setenv("PLIB_PASSWORD", "secret")
    creds = load_credentials()
    assert creds == Credentials("a@b.com", "secret")


def test_credentials_from_secrets_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("PLIB_EMAIL", raising=False)
    monkeypatch.delenv("PLIB_PASSWORD", raising=False)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "email").write_text("u@pku.edu.cn\n", encoding="utf-8")
    (secrets / "password").write_text("pw\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Avoid picking up a real ~/.config credentials file in CI/dev.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    creds = load_credentials()
    assert creds == Credentials("u@pku.edu.cn", "pw")
