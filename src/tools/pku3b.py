"""In-process pku3b backend, via the vendored :mod:`pypku3b` library.

Replaces the former subprocess wrapper around the external ``pku3b`` Rust
binary: the four surfaces PKU Captain uses (assignments, announcements,
coursetable, identity) are now driven **in-process** through
:class:`pypku3b.Client`, mirroring how plib/dean/treehole are integrated.
Credentials come from ``secrets/pku/{id,password}`` instead of pku3b's
``cfg.toml``. This module is deliberately **not** a Tool — it isolates the
client wiring, credential loading, and error-redaction shared by the three
pku3b Tool subclasses and ``bootstrap._sync_pku3b_identity_memory``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

_WEB_URL = "https://course.pku.edu.cn/"

try:  # graceful degradation when the vendored package is absent (treehole pattern)
    from pypku3b import Client as _Client
    from pypku3b import Credentials
    from pypku3b.errors import Pku3bError
except ModuleNotFoundError:  # pragma: no cover - exercised only without the vendor pkg
    _Client = None
    Credentials = None  # type: ignore[assignment,misc]

    class Pku3bError(Exception):  # type: ignore[no-redef]
        code = "error"

        def __init__(self, message: str, *, code: str | None = None) -> None:
            super().__init__(message)
            self.message = message
            if code is not None:
                self.code = code


_REPO_ROOT = Path(__file__).resolve().parents[2]
PKU_SECRETS_DIR = _REPO_ROOT / "secrets" / "pku"
_COOKIE_PATH = PKU_SECRETS_DIR / "cookies.json"
_CACHE_DIR = _REPO_ROOT / "data" / "pku3b_cache"

DEFAULT_TIMEOUT = 60.0

# (secrets_dir, timeout, credentials) -> a pypku3b.Client (or a test fake).
ClientFactory = Callable[..., Any]


class Pku3bUnavailableError(Pku3bError):
    """The vendored ``pypku3b`` package is not importable."""

    code = "not_installed"


def default_client_factory(
    *,
    secrets_dir: Path,
    timeout: float = DEFAULT_TIMEOUT,
    credentials: Any = None,
) -> Any:
    """Build a real :class:`pypku3b.Client` bound to this repo's secrets/cache."""
    if _Client is None:
        raise Pku3bUnavailableError(
            "pypku3b is not installed (vendored package missing); reinstall "
            "with `pip install -e .`"
        )
    return _Client(
        credentials=credentials,
        secrets_dir=secrets_dir,
        timeout=timeout,
        cookie_path=_COOKIE_PATH,
        cache_dir=_CACHE_DIR,
    )


def _read_secret(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def stored_credentials(secrets_dir: Path) -> Any:
    """Return :class:`pypku3b.Credentials` from ``secrets_dir``, or ``None``."""
    if Credentials is None:
        return None
    username = _read_secret(secrets_dir / "id")
    password = _read_secret(secrets_dir / "password")
    if username and password:
        return Credentials(username, password)
    return None


def secret_values(secrets_dir: Path) -> list[str]:
    """The secret strings to redact from any surfaced error text."""
    creds = stored_credentials(secrets_dir)
    return [creds.password] if creds else []


def assignment_submit_url(course_id: str, content_id: str) -> str | None:
    """The Blackboard "view/submit" page URL for one assignment, or ``None``.

    Deterministic from ``(course_id, content_id)`` — the Blackboard "view/
    submit" page for the assignment, built without any cache probing.
    """
    if not (course_id and content_id):
        return None
    query = urlencode(
        {
            "content_id": content_id,
            "course_id": course_id,
            "group_id": "",
            "mode": "view",
        }
    )
    return urljoin(_WEB_URL, f"/webapps/assignment/uploadAssignment?{query}")
