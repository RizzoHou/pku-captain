"""PlibClient — the authenticated HTTP client for pkuhub.cn.

Wraps a persistent ``requests.Session`` (cookie jar on disk) and exposes the
three operations the CLI needs: :meth:`search`, :meth:`material`, and
:meth:`download`. Login is lazy and self-healing — any request that the server
bounces to ``/login`` triggers a re-login from stored credentials and one
retry, so callers (agents especially) never have to log in explicitly or
handle a mid-task session expiry.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from . import config, parsers
from .config import DAILY_QUOTA, Credentials
from .errors import (
    AuthError,
    CredentialsError,
    NetworkError,
    NotFoundError,
    ParseError,
    QuotaError,
)
from .models import DownloadResult, Material, Profile, SearchPage

_USER_AGENT = "plib-cli/0.1 (+https://github.com/RizzoHou/plib-cli)"
_FILENAME_RE = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.IGNORECASE)
# Safety cap on auto-pagination so a pathological query can't loop forever. A
# course-material result set is realistically well under this; if a search ever
# hits it, the response's count stays below total, which signals the cap.
_MAX_SEARCH_PAGES = 50


class PlibClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        credentials: Credentials | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or config.base_url()).rstrip("/")
        self._credentials = credentials
        self.timeout = timeout
        # Cache of the server's "remaining downloads today", read lazily from
        # /profile and decremented as this client downloads (see quota_remaining).
        self._download_remaining: int | None = None

        self.session = requests.Session()
        self.session.headers["User-Agent"] = _USER_AGENT
        self._jar = config.cookie_jar()
        try:
            self._jar.load(ignore_discard=True)
        except (OSError, ValueError):
            pass
        self.session.cookies = self._jar  # type: ignore[assignment]

    # -- credentials -----------------------------------------------------

    def _creds(self) -> Credentials:
        if self._credentials is None:
            self._credentials = config.load_credentials()
        if self._credentials is None:
            raise CredentialsError(
                "no P-Lib credentials found. Set PLIB_EMAIL/PLIB_PASSWORD, "
                "create secrets/email + secrets/password, or "
                "~/.config/plib-cli/credentials/."
            )
        return self._credentials

    def _save_cookies(self) -> None:
        try:
            self._jar.save(ignore_discard=True)
        except OSError:
            pass

    # -- low-level request with self-healing auth ------------------------

    def _request(self, method: str, path: str, *, retry: bool = True, **kwargs):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", False)
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.Timeout as exc:
            raise NetworkError(f"request to {path} timed out") from exc
        except requests.RequestException as exc:
            raise NetworkError(f"request to {path} failed: {exc}") from exc

        if _is_login_redirect(resp) and retry:
            self.login()
            return self._request(method, path, retry=False, **kwargs)
        return resp

    def _get_html(self, path: str) -> str:
        resp = self._request("GET", path)
        if resp.status_code == 404:
            raise NotFoundError(f"{path} not found (404)")
        if _is_login_redirect(resp):
            raise AuthError("session is not authenticated and re-login failed")
        if resp.status_code != 200:
            raise NetworkError(f"GET {path} returned HTTP {resp.status_code}")
        return resp.text

    # -- login -----------------------------------------------------------

    def login(self) -> None:
        """Establish an authenticated session from stored credentials."""
        creds = self._creds()
        try:
            page = self.session.get(
                f"{self.base_url}/login", timeout=self.timeout, allow_redirects=True
            )
        except requests.RequestException as exc:
            raise NetworkError(f"could not load login page: {exc}") from exc

        token = _extract_csrf(page.text)
        if not token:
            raise AuthError("could not find csrf_token on the login page")

        try:
            resp = self.session.post(
                f"{self.base_url}/login?next=",
                data={
                    "email": creds.email,
                    "password": creds.password,
                    "csrf_token": token,
                    "remember": "y",
                    # pkuhub added a required "agree to terms" checkbox to the
                    # login form; omitting it re-renders /login with the flash
                    # "请先同意用户协议和隐私政策" and login fails.
                    "agree_terms": "y",
                    "submit": "登录",
                },
                timeout=self.timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise NetworkError(f"login request failed: {exc}") from exc

        # A successful login redirects to "/"; a failed one re-renders /login
        # (usually with a flash message) at HTTP 200.
        if urlparse(resp.url).path.rstrip("/") in ("/login",) or _looks_like_login_form(
            resp.text
        ):
            raise AuthError(
                "login failed — check the email/password in your credentials source"
            )
        self._save_cookies()

    # -- public operations ----------------------------------------------

    def search(
        self,
        query: str,
        *,
        type: str | None = None,
        time: str | None = None,
        sort: str = "relevance",
        page: int = 1,
    ) -> SearchPage:
        params = {
            "q": query,
            "page": str(page),
            "type": type or "",
            "time": time or "",
            "sort": sort,
        }
        qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        html = self._get_html(f"/search?{qs}")
        return parsers.parse_search(html, query=query, page=page, base_url=self.base_url)

    def search_all(
        self,
        query: str,
        *,
        type: str | None = None,
        time: str | None = None,
        sort: str = "relevance",
        limit: int | None = None,
        max_pages: int = _MAX_SEARCH_PAGES,
    ) -> SearchPage:
        """Search across all result pages and aggregate them into one page.

        The site paginates ~10 results per page; a single :meth:`search` call
        returns only one of them, so the default CLI uses this to surface the
        whole result set the way the browser does. Search is quota-free, so the
        extra HTTP requests are cheap. Results are de-duplicated by id (the
        site's ordering can shift between requests). Stops at ``limit`` if given,
        at ``total`` once reached, when a page adds nothing new, or at
        ``max_pages`` — a count below ``total`` in the result signals the cap.
        """
        first = self.search(query, type=type, time=time, sort=sort, page=1)
        total = first.total
        seen: set[int] = set()
        results = []
        for r in first.results:
            if r.id not in seen:
                seen.add(r.id)
                results.append(r)

        page = 1
        while True:
            if limit is not None and len(results) >= limit:
                break
            if total is not None and len(results) >= total:
                break
            if page >= max_pages:
                break
            page += 1
            nxt = self.search(query, type=type, time=time, sort=sort, page=page)
            if not nxt.results:
                break
            added = 0
            for r in nxt.results:
                if r.id not in seen:
                    seen.add(r.id)
                    results.append(r)
                    added += 1
            # An all-duplicate page means the site stopped advancing (ignored
            # the page param or wrapped) — stop rather than loop on it.
            if added == 0:
                break

        if limit is not None:
            results = results[:limit]
        return SearchPage(query=query, page=1, total=total, results=results)

    def profile(self) -> Profile:
        """Fetch and parse the logged-in account's /profile page.

        Goes through :meth:`_get_html` so it inherits the self-healing re-login
        (/profile is login-gated like everything else).
        """
        return parsers.parse_profile(self._get_html("/profile"))

    def quota_remaining(self, *, refresh: bool = False) -> int | None:
        """Server-reported downloads remaining today, cached on the client.

        The first call (or ``refresh=True``) reads /profile; later calls return
        the cached value, which :meth:`download` decrements as it consumes the
        allowance. Fails **open**: a transient network error or markup drift
        returns ``None`` (unknown) rather than raising, so a flaky /profile
        never aborts a download that would otherwise succeed — the server still
        enforces its own cap on the download itself.
        """
        if refresh or self._download_remaining is None:
            try:
                self._download_remaining = self.profile().download_remaining
            except (NetworkError, ParseError):
                return None
        return self._download_remaining

    def material(self, material_id: int) -> Material:
        html = self._get_html(f"/material/{material_id}")
        mat = parsers.parse_material(html, mid=material_id, base_url=self.base_url)
        if mat.title is None:
            raise ParseError(f"could not parse material {material_id} — markup changed?")
        return mat

    def _csrf_token(self, material_id: int) -> str | None:
        """CSRF token for the download POST (see :meth:`download`).

        pkuhub mints a per-session Flask-WTF token and renders it into every
        page's ``<meta name="csrf-token">``. Harvest it from the material page —
        the self-healing :meth:`_get_html` also (re-)authenticates as a side
        effect, so the token is guaranteed to match the live session before we
        POST it back.
        """
        return _extract_csrf(self._get_html(f"/material/{material_id}"))

    def download(
        self,
        material_id: int,
        dest_dir: str | Path = ".",
        *,
        force: bool = False,
    ) -> DownloadResult:
        if not force:
            remaining = self.quota_remaining()
            if remaining is not None and remaining <= 0:
                raise QuotaError(
                    f"no downloads remaining today (server cap is {DAILY_QUOTA}/day). "
                    "Use --force to attempt anyway, or wait for the daily reset."
                )

        # pkuhub switched /download/<id> from a plain GET link to a CSRF-guarded
        # POST: GET now returns HTTP 405, and the site's own csrf_helper.js sends
        # the token as the X-CSRFToken header on every unsafe same-origin fetch.
        # Mirror that exactly — harvest the session token, then POST it. retry is
        # off: _csrf_token just authenticated us, so a login bounce here is a real
        # failure, and re-posting the now-stale token would only 400.
        token = self._csrf_token(material_id)
        resp = self._request(
            "POST",
            f"/download/{material_id}",
            retry=False,
            allow_redirects=True,
            headers={"X-CSRFToken": token} if token else None,
        )
        if resp.status_code == 405:
            raise NetworkError(
                "download returned HTTP 405 — pkuhub rejected the POST method; "
                "the download endpoint may have changed again"
            )
        if resp.status_code == 404:
            raise NotFoundError(f"material {material_id} not found (404)")
        if _is_login_redirect(resp):
            raise AuthError("not authenticated for download and re-login failed")
        if resp.status_code != 200:
            # Note: if the server ever rejects an over-quota download by status
            # code (403/429) rather than an HTML body, it surfaces here as a
            # network_error, not quota_exceeded. Observed behaviour is an HTML
            # body (handled just below); revisit if a status-code path appears.
            raise NetworkError(f"download returned HTTP {resp.status_code}")

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type:
            raise QuotaError(_quota_message(resp.text) or "download was refused by the server")

        filename = _filename_from_response(resp, material_id)
        dest = Path(dest_dir).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        out_path = dest / filename
        # Different materials can share a Content-Disposition name (e.g. two
        # "26.zip"); prefix with the id rather than silently overwriting.
        if out_path.exists():
            filename = f"{material_id}-{filename}"
            out_path = dest / filename
        out_path.write_bytes(resp.content)

        # Reflect the consumed download in the cached server figure (if known),
        # so a batch and the final report stay accurate without re-fetching.
        if self._download_remaining is not None:
            self._download_remaining = max(0, self._download_remaining - 1)
        return DownloadResult(
            id=material_id,
            path=str(out_path),
            filename=filename,
            bytes=len(resp.content),
            quota_remaining=self._download_remaining,
        )


# -- module helpers ------------------------------------------------------


def _is_login_redirect(resp: requests.Response) -> bool:
    # Raw redirect (allow_redirects=False path, used by search/show): inspect
    # the Location header.
    if resp.status_code in (301, 302, 303, 307, 308):
        return "/login" in resp.headers.get("Location", "")
    # Followed redirect (allow_redirects=True path, used by download): the
    # server bounced an unauthenticated request all the way to the login page,
    # which arrives as a final HTTP 200. Detect it by the landing URL so a dead
    # session triggers re-login instead of masquerading as a quota refusal.
    return urlparse(resp.url).path.rstrip("/") == "/login"


def _extract_csrf(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    field = soup.select_one('input[name="csrf_token"]')
    if field and field.get("value"):
        return field["value"]
    meta = soup.select_one('meta[name="csrf-token"]')
    return meta.get("content") if meta else None


def _looks_like_login_form(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(
        soup.select_one('input[name="password"]')
        and soup.select_one('input[name="email"]')
    )


def _filename_from_response(resp: requests.Response, material_id: int) -> str:
    disposition = resp.headers.get("Content-Disposition", "")
    m = _FILENAME_RE.search(disposition)
    if m:
        name = unquote(m.group(1)).strip()
        if name:
            return Path(name).name
    # Fall back to the final URL path, then a generic name.
    tail = Path(urlparse(resp.url).path).name
    return tail or f"material-{material_id}.bin"


def _quota_message(html: str) -> str | None:
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    for needle in ("下载次数", "配额", "上限", "超过", "限制"):
        if needle in text:
            return text[:200]
    return None
