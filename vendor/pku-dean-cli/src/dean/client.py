"""HTTP client for dean.pku.edu.cn.

A thin wrapper over :class:`requests.Session` that centralizes the base URL,
a browser-like User-Agent, timeouts, and error normalization into
:class:`~dean.errors.DeanError`. All site responses are UTF-8.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .errors import DeanError

BASE_URL = "https://dean.pku.edu.cn"
WEB_URL = f"{BASE_URL}/web/"
INDEX_URL = f"{BASE_URL}/index.php"

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 pku-dean-cli/0.1"
)
DEFAULT_TIMEOUT = 30.0


class DeanClient:
    """Fetches HTML and files from the dean site."""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    # -- HTML ---------------------------------------------------------------

    def get_html(self, url: str, *, params: dict | None = None) -> str:
        """GET a page and return its decoded text, or raise :class:`DeanError`."""
        resp = self._get(url, params=params)
        resp.encoding = resp.encoding or "utf-8"
        return resp.text

    # -- File download ------------------------------------------------------

    def download(
        self,
        url: str,
        *,
        params: dict | None = None,
        out_dir: str | Path,
        filename: str | None = None,
    ) -> Path:
        """Download a file (following the download_down.php redirect) into ``out_dir``.

        Returns the path written. Filename is taken from ``filename``, else a
        Content-Disposition header, else the final URL's basename.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        resp = self._get(url, params=params, stream=True)
        name = filename or _filename_from_response(resp)
        dest = out / name
        try:
            with dest.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
        except OSError as exc:  # pragma: no cover - disk errors
            raise DeanError(f"could not write {dest}: {exc}", code="io_error") from exc
        return dest

    # -- internals ----------------------------------------------------------

    def _get(self, url: str, *, params: dict | None = None, stream: bool = False):
        try:
            resp = self.session.get(
                url, params=params, timeout=self.timeout, stream=stream
            )
        except requests.Timeout as exc:
            raise DeanError(f"request to {url} timed out", code="timeout") from exc
        except requests.RequestException as exc:
            raise DeanError(f"network error for {url}: {exc}", code="network_error") from exc
        if resp.status_code >= 400:
            raise DeanError(
                f"HTTP {resp.status_code} for {resp.url}", code="http_error"
            )
        return resp


_DISPOSITION_RE = re.compile(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", re.IGNORECASE)
_SAFE_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _filename_from_response(resp: requests.Response) -> str:
    disp = resp.headers.get("Content-Disposition", "")
    m = _DISPOSITION_RE.search(disp)
    if m:
        return _sanitize(unquote(m.group(1)))
    path = urlparse(resp.url).path
    base = Path(unquote(path)).name
    return _sanitize(base) or "download.bin"


def _sanitize(name: str) -> str:
    return _SAFE_RE.sub("_", name).strip().strip(".") or "download.bin"
