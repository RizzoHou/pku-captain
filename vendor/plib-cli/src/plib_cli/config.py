"""Configuration: credentials, paths, and the per-day download-quota counter.

Credentials are resolved in priority order so the same code works for a human
shell, an agent, and local development:

1. ``PLIB_EMAIL`` / ``PLIB_PASSWORD`` environment variables.
2. A ``secrets/`` directory (files ``email`` and ``password``) — found by
   walking up from the current directory. This is the dev-time source and is
   gitignored.
3. ``~/.config/plib-cli/credentials`` (``email``/``password`` files).

Session cookies persist in ``~/.cache/plib-cli/cookies.txt`` (overridable via
``PLIB_CACHE_DIR``) so login survives across invocations — essential for a CLI
that agents call once per action.

The download quota is no longer mirrored locally: the server reports the true
remaining count on /profile, which the client reads directly (see
``PlibClient.quota_remaining``). :data:`DAILY_QUOTA` is kept only as the known
account cap used in the over-quota error message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from http.cookiejar import LWPCookieJar
from pathlib import Path

DEFAULT_BASE_URL = "https://pkuhub.cn"
DAILY_QUOTA = 10


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str


def _read(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _find_secrets_dir(start: Path | None = None) -> Path | None:
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "secrets"
        if (candidate / "email").is_file() and (candidate / "password").is_file():
            return candidate
    return None


def load_credentials() -> Credentials | None:
    email = os.environ.get("PLIB_EMAIL")
    password = os.environ.get("PLIB_PASSWORD")
    if email and password:
        return Credentials(email.strip(), password.strip())

    secrets = _find_secrets_dir()
    if secrets:
        email = _read(secrets / "email")
        password = _read(secrets / "password")
        if email and password:
            return Credentials(email, password)

    config = config_dir()
    email = _read(config / "credentials" / "email")
    password = _read(config / "credentials" / "password")
    if email and password:
        return Credentials(email, password)

    return None


def base_url() -> str:
    return os.environ.get("PLIB_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def config_dir() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / "plib-cli" if root else Path.home() / ".config" / "plib-cli"


def cache_dir() -> Path:
    root = os.environ.get("PLIB_CACHE_DIR")
    base = Path(root) if root else Path.home() / ".cache" / "plib-cli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cookie_jar() -> LWPCookieJar:
    return LWPCookieJar(str(cache_dir() / "cookies.txt"))
