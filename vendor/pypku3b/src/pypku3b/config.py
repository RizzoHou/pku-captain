"""Credential and cookie-path resolution.

Credentials are read from a plaintext ``secrets/pku/{id,password}`` layout (the
same convention the sibling plib/treehole tools use) rather than pku3b's
AES-encrypted ``cfg.toml`` — this keeps the library free of a crypto dependency
and lets the host app own its own secrets directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Credentials:
    """PKU IAAA login: ``username`` is the student id, ``password`` the IAAA
    portal password."""

    username: str
    password: str


def _read(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def load_credentials(secrets_dir: Path | str | None = None) -> Credentials | None:
    """Resolve credentials, in priority order.

    1. env ``PKU_USERNAME`` / ``PKU_PASSWORD``;
    2. ``<secrets_dir>/{id,password}`` when *secrets_dir* is given;
    3. ``~/.config/pypku3b/{id,password}``.

    Returns ``None`` when neither field can be resolved (the caller decides
    whether that is fatal).
    """
    env_user = os.environ.get("PKU_USERNAME")
    env_pass = os.environ.get("PKU_PASSWORD")
    if env_user and env_pass:
        return Credentials(env_user, env_pass)

    candidates: list[Path] = []
    if secrets_dir is not None:
        candidates.append(Path(secrets_dir))
    candidates.append(Path.home() / ".config" / "pypku3b")

    for directory in candidates:
        username = _read(directory / "id")
        password = _read(directory / "password")
        if username and password:
            return Credentials(username, password)
    return None


def default_cookie_path() -> Path:
    """Where the session cookie jar is persisted by default."""
    return Path.home() / ".cache" / "pypku3b" / "cookies.json"
