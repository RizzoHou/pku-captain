"""Error type carrying a machine-readable code alongside a message.

The CLI serializes these into the JSON envelope's ``error`` object so that
programmatic consumers (e.g. pku-captain) can branch on ``code`` rather than
parsing prose.
"""

from __future__ import annotations


class DeanError(Exception):
    """A failure while fetching or parsing a dean.pku.edu.cn resource."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
