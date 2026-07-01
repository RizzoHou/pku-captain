"""Exception hierarchy for plib-cli.

All errors derive from :class:`PlibError` so callers (and the CLI's JSON
error envelope) can catch a single base. Each carries a short, stable
``code`` string so agents can branch on the failure kind without parsing
prose.
"""

from __future__ import annotations


class PlibError(Exception):
    """Base for every error raised by plib-cli."""

    code = "error"


class CredentialsError(PlibError):
    """No usable email/password was found (env, secrets/, or config dir)."""

    code = "no_credentials"


class AuthError(PlibError):
    """Login failed, or the session could not be (re)established."""

    code = "auth_failed"


class NotFoundError(PlibError):
    """A material/course id does not exist (server returned 404)."""

    code = "not_found"


class QuotaError(PlibError):
    """The daily download quota would be exceeded (early client guard or server)."""

    code = "quota_exceeded"


class NetworkError(PlibError):
    """A transport-level failure (timeout, connection refused, etc.)."""

    code = "network_error"


class ParseError(PlibError):
    """The HTML did not match the expected structure — the site likely changed."""

    code = "parse_error"
