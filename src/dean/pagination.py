"""Page-bar parsing for the dean site's paginated listings.

Listings carry a ``<div id="page_bar">`` whose ``a.last_page`` link points at
the final page (``...php?page=N``). An empty page_bar means a single page.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_PAGE_RE = re.compile(r"[?&]page=(\d+)")


def parse_last_page(soup: BeautifulSoup) -> int:
    """Return the last page number from the page bar (default 1)."""
    bar = soup.select_one("#page_bar")
    if bar is None:
        return 1
    pages = [int(m.group(1)) for a in bar.find_all("a")
             if (m := _PAGE_RE.search(a.get("href") or ""))]
    return max(pages) if pages else 1
