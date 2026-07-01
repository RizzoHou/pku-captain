"""IAAA login → an authenticated Identity.

Ported from scripts/probe_login.py, which proved this chain live. The E21
safety discipline is the load-bearing part:

  * oauthlogin.do is the ONLY call that counts toward the E21 30-min lockout.
  * We attempt it AT MOST ONCE. We retry only ConnectionError/TLS-handshake
    failures (no HTTP response = IAAA never got the request = not an attempt).
    A read-timeout or any HTTP response is NEVER retried.
  * E01 (wrong creds) and E21 (lockout) are fatal — surface, never loop.
"""

from __future__ import annotations

import base64
import json
import time
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import endpoints
from .errors import IAAALockout, LoginFailed
from .session import Identity


def new_login_uuid() -> str:
    """A fresh device id, shaped like the SPA's 32-hex-uppercase fallback."""
    return _uuid.uuid4().hex.upper()


@dataclass
class Credentials:
    uid: str
    password: str

    @classmethod
    def from_dir(cls, secrets_dir: str | Path) -> "Credentials":
        d = Path(secrets_dir)
        return cls(
            uid=(d / "id").read_text().strip(),
            password=(d / "password").read_text().strip(),
        )


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = endpoints.USER_AGENT
    # Connect-only retries: a failed connection is pre-send (safe to retry for any
    # method). read/status are NOT auto-retried — that protects the login POST.
    retry = Retry(total=5, connect=5, read=0, status=0,
                  backoff_factor=0.8, allowed_methods=None)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _get_retry(s: requests.Session, url: str, *, tries: int = 5, **kw) -> requests.Response:
    """Retry idempotent GETs on any transient network error (GET is safe to repeat)."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return s.get(url, **kw)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(0.8 * (i + 1))
    raise LoginFailed(f"network error on GET {url.split('?')[0]}: {last}")


def _post_login_once(s: requests.Session, *, tries: int = 5, **kw) -> requests.Response:
    """POST oauthlogin, retrying ONLY connection/TLS failures (no request delivered).

    A ReadTimeout or any returned HTTP response stops immediately — we must never
    risk a second authentication attempt against the E21 lockout."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return s.post(endpoints.IAAA_OAUTH_LOGIN, **kw)
        except requests.exceptions.ConnectionError as e:  # TLS handshake EOF, connect refused
            last = e
            time.sleep(0.8 * (i + 1))
        # ReadTimeout / other: do NOT retry — the request may have been processed.
    raise LoginFailed(f"could not reach IAAA oauthlogin (connection failures): {last}")


def login(
    creds: Credentials,
    *,
    login_uuid: str | None = None,
    otp: str = "",
    session: requests.Session | None = None,
) -> Identity:
    """Run the 5-step IAAA → treehole handoff and return a fresh Identity.

    login_uuid defaults to a new random device id. Pass an existing one to keep
    a previously SMS-verified device identity (re-minting the JWT under the same
    uuid may avoid re-verification — unverified, see protocol doc).
    """
    login_uuid = login_uuid or new_login_uuid()
    s = session or _build_session()

    # Step 1: treehole starts OAuth → session cookies + the IAAA redirect target.
    r = _get_retry(s, endpoints.REDIRECT_IAAA,
                   params={"version": 3, "uuid": login_uuid, "plat": "web"},
                   allow_redirects=False, timeout=20)
    loc = r.headers.get("location", "")
    if "redirectUrl=" not in loc:
        raise LoginFailed(f"redirect_iaaa_login gave no redirectUrl (loc={loc[:120]!r})")
    redir_url = unquote(loc.split("redirectUrl=", 1)[1])

    # Step 2: IAAA login (CONSUMES one E21 attempt; at most once).
    r = _post_login_once(s, data={
        "appid": endpoints.APPID, "userName": creds.uid, "password": creds.password,
        "randCode": "", "smsCode": "", "otpCode": otp, "redirUrl": redir_url,
    }, timeout=20)
    try:
        body = r.json()
    except ValueError:
        raise LoginFailed(f"IAAA oauthlogin returned non-JSON (http {r.status_code})") from None
    token = body.get("token")
    if not token:
        code = (body.get("errors") or {}).get("code") or body.get("code") or ""
        msg = (body.get("errors") or {}).get("msg") or body.get("msg") or body.get("message") or str(body)[:160]
        if code == "E21":
            raise IAAALockout(f"E21 lockout (30 min): {msg}")
        raise LoginFailed(f"IAAA rejected login [{code or '??'}]: {msg}")

    # Step 3: hand the IAAA token back to treehole's CAS callback → the app JWT.
    sep = "&" if "?" in redir_url else "?"
    r = _get_retry(s, redir_url + f"{sep}token={token}", allow_redirects=True, timeout=20)
    q = parse_qs(urlparse(r.url).query)
    jwt = (q.get("token") or [""])[0]
    if not jwt:
        raise LoginFailed(f"CAS callback returned no JWT (final url {r.url[:160]!r})")
    expires_in = (q.get("expires_in") or [""])[0]
    uid = (q.get("uid") or [""])[0] or creds.uid

    # Decode JWT (no verification) to recover sub/exp.
    sub, exp = None, None
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        sub, exp = claims.get("sub"), claims.get("exp")
    except Exception:
        pass

    return Identity(
        jwt=jwt,
        login_uuid=login_uuid,
        expires_in=int(expires_in) if str(expires_in).isdigit() else exp,
        uid=sub or uid,
        cookies=s.cookies.get_dict(),
    )
