"""Thin ``requests.Session`` wrapper with a persistable cookie jar.

Mirrors pku3b's low-level client: a single session with a fixed desktop
User-Agent and a JSON cookie jar so a prior login's cookies survive across
processes (the session-reuse mechanism that lets most calls skip re-login/OTP).
It can also warm-start from pku3b's own ``ua.json`` so an existing pku3b login
is reused verbatim.
"""

from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from typing import Any

import requests

from .errors import NetworkError

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


def default_ca_bundle() -> str | bool:
    """Resolve a CA bundle, preferring the OS trust store over certifi.

    ``course.pku.edu.cn``'s GlobalSign chain verifies against the OS trust store
    but not always against Python's bundled certifi (which can lag behind newer
    intermediates). pku3b succeeds because its Rust ``native-tls`` uses the OS
    store, so we mirror that: honour ``SSL_CERT_FILE``, else the OpenSSL default
    CA file, else fall back to certifi (``True``).
    """
    env = os.environ.get("SSL_CERT_FILE")
    if env and Path(env).exists():
        return env
    try:
        cafile = ssl.get_default_verify_paths().openssl_cafile
    except Exception:  # pragma: no cover - platform dependent
        cafile = None
    if cafile and Path(cafile).exists():
        return cafile
    return True


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        cookie_path: Path | str | None = None,
        seed_cookie_path: Path | str | None = None,
        verify: str | bool | None = None,
    ) -> None:
        self.timeout = timeout
        self.cookie_path = Path(cookie_path) if cookie_path is not None else None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.verify = default_ca_bundle() if verify is None else verify

        loaded = False
        if self.cookie_path is not None and self.cookie_path.exists():
            loaded = self._load_cookies(self.cookie_path)
        if not loaded and seed_cookie_path is not None:
            seed = Path(seed_cookie_path)
            if seed.exists():
                # pku3b's ua.json warm-start (read-only seed).
                self._load_pku3b_cookies(seed)

    # -- requests -----------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        try:
            return self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network
            raise NetworkError(f"{method} {url} failed: {exc}") from exc

    # -- cookie persistence -------------------------------------------------

    def save_cookies(self, path: Path | str | None = None) -> None:
        target = Path(path) if path is not None else self.cookie_path
        if target is None:
            return
        records = [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
            }
            for c in self.session.cookies
        ]
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: concurrent dashboard refreshes may share this file.
        tmp = target.with_suffix(target.suffix + f".tmp-{os.getpid()}")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, target)

    def _load_cookies(self, path: Path) -> bool:
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(records, list):
            return False
        count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            name = record.get("name")
            value = record.get("value")
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            self.session.cookies.set(
                name,
                value,
                domain=record.get("domain") or "",
                path=record.get("path") or "/",
            )
            count += 1
        return count > 0

    def _load_pku3b_cookies(self, path: Path) -> bool:
        """Import cookies from pku3b's ``ua.json`` (cookie_store JSON format)."""
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(records, list):
            return False
        count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            raw = record.get("raw_cookie")
            if not isinstance(raw, str) or "=" not in raw:
                continue
            pair = raw.split(";", 1)[0]
            name, _, value = pair.partition("=")
            name, value = name.strip(), value.strip()
            if not name:
                continue
            domain = ""
            dom = record.get("domain")
            if isinstance(dom, dict):
                domain = dom.get("HostOnly") or dom.get("Suffix") or ""
            path_field = record.get("path")
            cookie_path = "/"
            if isinstance(path_field, list) and path_field:
                cookie_path = str(path_field[0])
            self.session.cookies.set(name, value, domain=domain, path=cookie_path)
            count += 1
        return count > 0
