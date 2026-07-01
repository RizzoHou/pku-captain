"""Authentication hook — stub for future IAAA-gated resources.

Every resource the CLI currently exposes (sidebar, rules, downloads, open-info)
is public and needs no login. The only dean content behind PKU's central IAAA
(``iaaa.pku.edu.cn``) login is the separate ``service/`` portal — course
selection, room booking, grade queries — which is out of scope for now.

When that scope is added, implement the OAuth flow here and have callers read
credentials from ``secrets/id`` and ``secrets/password`` via :func:`load_credentials`.
"""

from __future__ import annotations

from pathlib import Path

from .errors import DeanError

# Repo-root/secrets — works when running from a source checkout.
_SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


def load_credentials(secrets_dir: str | Path | None = None) -> tuple[str, str]:
    """Read the stored PKU id/password pair.

    Returns ``(student_id, password)``. Raises :class:`DeanError` if either file
    is missing or empty. Only needed once IAAA-gated resources are implemented.
    """
    base = Path(secrets_dir) if secrets_dir is not None else _SECRETS_DIR
    student_id = _read(base / "id")
    password = _read(base / "password")
    if not student_id or not password:
        raise DeanError(
            f"missing credentials in {base} (need both 'id' and 'password')",
            code="no_credentials",
        )
    return student_id, password


def login(*_args, **_kwargs):  # pragma: no cover - not implemented yet
    """Placeholder for the IAAA OAuth login flow."""
    raise DeanError(
        "IAAA login is not implemented; all current resources are public",
        code="not_implemented",
    )


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
