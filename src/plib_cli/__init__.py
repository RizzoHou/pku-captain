"""plib-cli — a client for P-Lib (pkuhub.cn) course materials.

The public surface is :class:`plib_cli.client.PlibClient` (importable as a
library) and the ``plib`` console script (:mod:`plib_cli.cli`). The site has
no JSON API, so the client logs in with an email/password account, keeps a
persistent cookie jar, scrapes the server-rendered HTML, and downloads files
through the authenticated session.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
