"""Probe the PKU treehole IAAA login flow and API shapes.

Discovery script (not the final CLI). Reads credentials from ``secrets/``
so they never appear on the command line. Run with no OTP for a dry run
(redirect + isMobileAuthen only — no OTP consumed); pass ``--otp 123456``
for the full login + endpoint probe.

Only ``oauthlogin.do`` consumes an OTP attempt; too many failures →
IAAA error E21 (30-min lockout), so the dry run validates everything
else first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"

IAAA_IS_MOBILE = "https://iaaa.pku.edu.cn/iaaa/isMobileAuthen.do"
IAAA_OAUTH_LOGIN = "https://iaaa.pku.edu.cn/iaaa/oauthlogin.do"
APPID = "PKU Helper"
TH = "https://treehole.pku.edu.cn"
REDIRECT_IAAA = TH + "/chapi/redirect_iaaa_login"
UUID = "probe-uuid-0001"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def req(s, method, url, *, tries=6, **kw):
    """Retry on transient connection/TLS errors (no HTTP response received).

    Safe for oauthlogin: a handshake failure means IAAA never got the
    request, so it does not count toward the E21 lockout. Once any HTTP
    response is returned, we stop — even an error response.
    """
    import time
    last = None
    for i in range(tries):
        try:
            return s.request(method, url, **kw)
        except requests.exceptions.RequestException as e:
            last = e
            print(f"  [retry {i + 1}/{tries}] {type(e).__name__} on {method} {url.split('?')[0]}")
            time.sleep(0.8 * (i + 1))
    raise last


def hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def show(resp: requests.Response, label: str, body_chars: int = 800) -> None:
    print(f"[{label}] {resp.request.method} {resp.url} -> {resp.status_code}")
    loc = resp.headers.get("location")
    if loc:
        print(f"  location: {loc}")
    ctype = resp.headers.get("content-type", "")
    txt = resp.text or ""
    if "json" in ctype or txt.strip().startswith("{"):
        try:
            print("  json:", json.dumps(resp.json(), ensure_ascii=False)[:body_chars])
            return
        except Exception:
            pass
    print(f"  body[:{body_chars}]: {txt[:body_chars]!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--otp", default="", help="6-digit IAAA mobile-token code")
    ap.add_argument("--login", action="store_true",
                    help="proceed through oauthlogin (use when authenMode=='否')")
    args = ap.parse_args()

    uid = (SECRETS / "id").read_text().strip()
    password = (SECRETS / "password").read_text().strip()
    print(f"uid: {uid[:2]}***{uid[-2:]} (len={len(uid)})  password: ***(len={len(password)})")

    s = requests.Session()
    s.headers["User-Agent"] = UA
    retry = Retry(total=6, connect=6, read=6, backoff_factor=0.8,
                  status_forcelist=[502, 503, 504], allowed_methods=None)
    s.mount("https://", HTTPAdapter(max_retries=retry))

    # Step 1: treehole kicks off OAuth — capture _session / XSRF cookies + IAAA redirect.
    hr("1. redirect_iaaa_login (capture session cookies)")
    r = s.get(REDIRECT_IAAA, params={"version": 3, "uuid": UUID, "plat": "web"},
              allow_redirects=False, timeout=20)
    show(r, "redirect_iaaa_login")
    iaaa_loc = r.headers.get("location", "")
    # Derive the redirUrl IAAA expects to bounce back to.
    redir_url = ""
    if "redirectUrl=" in iaaa_loc:
        from urllib.parse import unquote
        redir_url = unquote(iaaa_loc.split("redirectUrl=", 1)[1])
    print(f"  derived redirUrl: {redir_url}")
    print(f"  cookies now: {list(s.cookies.keys())}")

    # Step 2: is OTP required? (no OTP consumed) — non-fatal if it flakes.
    hr("2. isMobileAuthen")
    try:
        r = s.get(IAAA_IS_MOBILE, params={"appId": APPID, "userName": uid, "_rand": "0.123"},
                  timeout=20)
        show(r, "isMobileAuthen")
    except Exception as e:
        print("  isMobileAuthen flaked (non-fatal, dry run already confirmed 否):", e)

    if not args.otp and not args.login:
        print("\n[dry run] stopping before oauthlogin. "
              "Re-run with --login (and --otp <code> if IAAA needs one).")
        return 0

    # Step 3: IAAA oauth login (CONSUMES one OTP attempt).
    hr("3. oauthlogin.do")
    r = req(s, "POST", IAAA_OAUTH_LOGIN, data={
        "appid": APPID, "userName": uid, "password": password,
        "randCode": "", "smsCode": "", "otpCode": args.otp,
        "redirUrl": redir_url,
    }, timeout=20)
    show(r, "oauthlogin")
    try:
        token = r.json().get("token")
    except Exception:
        token = None
    if not token:
        print("  !! no IAAA token — aborting (check OTP / lockout).")
        return 1
    print(f"  IAAA token: {token[:12]}...")

    # Step 4: hand the IAAA token back to treehole's CAS callback → get the app JWT.
    hr("4. cas_iaaa_login callback (extract app JWT)")
    sep = "&" if "?" in redir_url else "?"
    r = req(s, "GET", redir_url + f"{sep}token={token}", allow_redirects=True, timeout=20)
    print(f"[cas_callback] final url -> {r.status_code}")
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(r.url).query)
    jwt = (q.get("token") or [""])[0]
    expires_in = (q.get("expires_in") or [""])[0]
    if not jwt:
        print("  !! no JWT in callback url:", r.url[:200])
        return 1
    # Decode JWT payload (no verification) just to confirm sub/exp.
    import base64
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        print(f"  JWT sub={claims.get('sub')} exp={claims.get('exp')} (≈30d)")
    except Exception as e:
        print("  jwt decode note:", e)
    s.headers["Authorization"] = f"Bearer {jwt}"
    print(f"  cookies now: {list(s.cookies.keys())}")

    # Step 5: authenticated reads against the CORRECT /chapi base.
    base = TH + "/chapi"
    hr("5. whoami + bookmark groups")
    r = s.get(base + "/api/v3/users/info", timeout=20)
    show(r, "users/info", body_chars=500)
    r = s.get(base + "/api/v3/bookmark/list", params={"page": 1, "limit": 30}, timeout=20)
    show(r, "bookmark/list (关注分组)", body_chars=800)

    hr("6. 关注 list  (hole/list?is_follow=1)")
    r = s.get(base + "/api/v3/hole/list",
              params={"is_follow": 1, "page": 1, "limit": 20}, timeout=20)
    first_pid = None
    try:
        data = r.json()
        holes = data.get("data", {}).get("list") or data.get("list") or []
        print(f"  status {r.status_code}  followed holes returned: {len(holes)}")
        for h in holes[:10]:
            pid = h.get("pid")
            first_pid = first_pid or pid
            txt = (h.get("text") or "").replace("\n", " ")[:50]
            print(f"   #{pid}  reply={h.get('reply')}  like={h.get('likenum')}  "
                  f"grp={h.get('attention_info', {}).get('bookmark_id')}  text={txt!r}")
    except Exception as e:
        print("  parse error:", e, "| raw:", (r.text or "")[:300])

    if first_pid:
        hr(f"7. comments of #{first_pid}  (comment/list)")
        r = s.get(base + "/api/v3/comment/list",
                  params={"pid": first_pid, "page": 1, "limit": 10}, timeout=20)
        try:
            data = r.json()
            cmts = data.get("data", {}).get("list") or data.get("list") or []
            print(f"  status {r.status_code}  comments returned: {len(cmts)}")
            for c in cmts[:8]:
                txt = (c.get("text") or "").replace("\n", " ")[:60]
                print(f"   cid={c.get('cid')}  [{c.get('name_tag')}]  {txt!r}")
        except Exception as e:
            print("  parse error:", e, "| raw:", (r.text or "")[:300])

    # Persist the session (JWT + cookies) for the real CLI to reuse.
    out = SECRETS / "session.json"
    out.write_text(json.dumps({"jwt": jwt, "expires_in": expires_in,
                               "uid": claims.get("sub") if "claims" in dir() else None,
                               "cookies": s.cookies.get_dict()},
                              ensure_ascii=False, indent=2))
    print(f"\nsaved session -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
