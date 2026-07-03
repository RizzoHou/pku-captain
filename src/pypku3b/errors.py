"""Exception hierarchy for :mod:`pypku3b`.

Every error carries a stable ``.code`` string so downstream consumers (e.g. a
Tool wrapper surfacing errors to an LLM) can branch on the failure kind without
string-matching messages. Mirrors the ``PlibError``/``DeanError`` convention of
the sibling vendored libraries.
"""

from __future__ import annotations


class Pku3bError(Exception):
    """Base class for all pypku3b errors."""

    code: str = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class ConfigError(Pku3bError):
    """Missing or malformed credentials/configuration."""

    code = "config_error"


class NetworkError(Pku3bError):
    """A transport-level failure (timeout, connection reset, DNS, ...)."""

    code = "network_error"


class AuthError(Pku3bError):
    """IAAA/Blackboard/portal login failed (bad password, expired session)."""

    code = "auth_error"


class NeedOTP(AuthError):
    """The portal requires a phone-token OTP that was not supplied/was wrong.

    Raised when IAAA reports the login context needs OTP and none was given, or
    when IAAA returns error ``E05`` (OTP incorrect).
    """

    code = "need_otp"


class IAAALockout(AuthError):
    """IAAA error ``E21`` — too many attempts; locked out for ~30 minutes."""

    code = "iaaa_lockout"


class ParseError(Pku3bError):
    """A response could not be parsed into the expected shape."""

    code = "parse_error"
