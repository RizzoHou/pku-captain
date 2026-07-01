"""The identity bundle and its on-disk store.

Identity = the device identity (login_uuid) + the 30-day JWT + (optional) cookies.
Empirically, reads need only jwt + uuid; cookies are kept for write actions and
API-drift insurance but are not required for the monitor path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import endpoints

# Backward-compat shim: the original probe minted its JWT under this fixed login
# uuid and secrets/session.json predates the login_uuid field. Fresh logins
# generate a random uuid (see auth.new_login_uuid); this default only keeps the
# existing verified session readable.
_LEGACY_LOGIN_UUID = "probe-uuid-0001"


@dataclass
class Identity:
    """Everything needed to authenticate as the logged-in device."""

    jwt: str
    login_uuid: str = _LEGACY_LOGIN_UUID
    expires_in: int | None = None      # unix ts; echoes the JWT exp
    uid: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def uuid_header(self) -> str:
        """The value for the `uuid` request header."""
        return endpoints.UUID_PREFIX + self.login_uuid

    def to_dict(self) -> dict[str, Any]:
        return {
            "jwt": self.jwt,
            "login_uuid": self.login_uuid,
            "expires_in": self.expires_in,
            "uid": self.uid,
            "cookies": self.cookies,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Identity":
        return cls(
            jwt=d["jwt"],
            login_uuid=d.get("login_uuid") or _LEGACY_LOGIN_UUID,
            expires_in=d.get("expires_in"),
            uid=d.get("uid"),
            cookies=d.get("cookies") or {},
        )


class SessionStore:
    """Loads/saves an Identity as JSON. Writes atomically so a crash mid-write
    can't leave a half-written JWT (which would force a full re-login + re-SMS)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> Identity:
        return Identity.from_dict(json.loads(self.path.read_text()))

    def load_or_none(self) -> Identity | None:
        return self.load() if self.exists() else None

    def save(self, identity: Identity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(identity.to_dict(), ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)  # atomic on POSIX
