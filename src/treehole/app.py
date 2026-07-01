"""Wiring helpers: build a ready client/monitor from a secrets directory.

This is the seam the pku-captain agent imports. Paths are explicit so the agent
can point them wherever it keeps its own state.
"""

from __future__ import annotations

from pathlib import Path

from .auth import Credentials, login
from .client import TreeholeClient
from .errors import AuthError
from .monitor import Monitor
from .session import Identity, SessionStore
from .state import StateStore


def _relogin_factory(creds: Credentials, store: SessionStore):
    """A relogin callable that reuses the stored login_uuid so the re-minted JWT
    keeps the same (possibly SMS-verified) device identity."""
    def relogin() -> Identity:
        existing = store.load_or_none()
        return login(creds, login_uuid=existing.login_uuid if existing else None)
    return relogin


def build_client(
    secrets_dir: str | Path = "secrets",
    *,
    session_path: str | Path | None = None,
    allow_relogin: bool = True,
) -> TreeholeClient:
    """Build an authenticated client.

    Loads the cached session if present; otherwise logs in (needs id/password in
    secrets_dir). If credentials are present, wires transparent re-login on 401.
    """
    secrets_dir = Path(secrets_dir)
    store = SessionStore(session_path or secrets_dir / "session.json")

    have_creds = (secrets_dir / "id").exists() and (secrets_dir / "password").exists()
    relogin = None
    if allow_relogin and have_creds:
        relogin = _relogin_factory(Credentials.from_dir(secrets_dir), store)

    identity = store.load_or_none()
    if identity is None:
        if not have_creds:
            raise AuthError(
                f"no cached session at {store.path} and no credentials in {secrets_dir}"
            )
        identity = login(Credentials.from_dir(secrets_dir))
        store.save(identity)

    return TreeholeClient(identity, store=store, relogin=relogin)


def build_monitor(
    secrets_dir: str | Path = "secrets",
    *,
    session_path: str | Path | None = None,
    state_path: str | Path = "state.json",
    allow_relogin: bool = True,
) -> Monitor:
    client = build_client(secrets_dir, session_path=session_path, allow_relogin=allow_relogin)
    return Monitor(client, StateStore(state_path))
