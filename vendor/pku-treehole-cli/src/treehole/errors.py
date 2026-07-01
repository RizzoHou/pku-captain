"""Exception hierarchy. Fail loud — never let an auth/gate failure look like
"all caught up" to a monitor an agent relies on.
"""

from __future__ import annotations


class TreeholeError(Exception):
    """Base for everything this package raises."""


class AuthError(TreeholeError):
    """Authentication is broken (bad/expired JWT, 401). Self-healable by re-login
    if credentials are available."""


class NeedSMSVerification(AuthError):
    """Content endpoint returned code 40002. The JWT is valid but the device
    identity (uuid) is not SMS-verified. A human with the bound phone must run
    send_sms() → verify_sms(code). Re-login does NOT clear this and would burn an
    E21 attempt, so callers must surface it, not retry."""


class LoginFailed(AuthError):
    """IAAA rejected the credentials (E01) or login returned no token. Fatal —
    do not retry, the password is wrong."""


class IAAALockout(AuthError):
    """IAAA error E21: too many failed attempts → 30-minute lockout. Stop."""


class APIError(TreeholeError):
    """A treehole endpoint returned a non-success code that isn't an auth gate."""

    def __init__(self, message: str, *, code: int | None = None, path: str | None = None):
        super().__init__(message)
        self.code = code
        self.path = path
