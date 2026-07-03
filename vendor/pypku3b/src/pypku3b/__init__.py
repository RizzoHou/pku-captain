"""pypku3b — a pure-Python reimplementation of the used subset of pku3b.

Public surface (import in-process, like the sibling plib/dean/treehole libs)::

    from pypku3b import Client, Credentials
    client = Client(secrets_dir="secrets/pku")
    assignments = client.list_assignments()
    announcements = client.list_announcements()
    identity = client.get_identity()
    table = client.get_coursetable()
"""

from __future__ import annotations

from .client import Client
from .config import Credentials, load_credentials
from .errors import (
    AuthError,
    ConfigError,
    IAAALockout,
    NeedOTP,
    NetworkError,
    ParseError,
    Pku3bError,
)
from .models import Announcement, Assignment, Attachment, CourseTable, Identity

__version__ = "0.1.0"

__all__ = [
    "Client",
    "Credentials",
    "load_credentials",
    "Assignment",
    "Announcement",
    "Attachment",
    "Identity",
    "CourseTable",
    "Pku3bError",
    "ConfigError",
    "NetworkError",
    "AuthError",
    "NeedOTP",
    "IAAALockout",
    "ParseError",
    "__version__",
]
