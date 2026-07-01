"""Drive treehole's SMS verification (the content-access gate, code 40002).

Two phases, sharing the cached JWT+cookies in secrets/session.json:

    python scripts/verify_sms.py --send          # triggers an SMS to the bound phone
    python scripts/verify_sms.py --code 123456    # verifies, then fetches real content

Run --code promptly — SMS codes expire. After a successful verify it
re-fetches the public timeline, a hole's comments, and the 关注 list to
prove content reads now work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://treehole.pku.edu.cn/chapi"
SPATH = ROOT / "secrets" / "session.json"

# Device identity. The SPA sends header `uuid = "Web_PKUHOLE_2.0.0_WEB_UUID_" + e`
# where e is the same id passed to redirect_iaaa_login. The existing JWT was
# minted with login uuid "probe-uuid-0001", so we keep the header consistent
# with that to give the verify-time / login-time binding hypotheses their best shot.
LOGIN_UUID = "probe-uuid-0001"
UUID_HEADER = "Web_PKUHOLE_2.0.0_WEB_UUID_" + LOGIN_UUID


def client():
    S = json.loads(SPATH.read_text())
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
        "Authorization": f"Bearer {S['jwt']}",
        "Accept": "application/json",
        "uuid": UUID_HEADER,          # the missing device-identity header
    })
    for k, v in (S.get("cookies") or {}).items():
        s.cookies.set(k, v)
    return s, S


def save_cookies(s, S):
    S["cookies"] = {**(S.get("cookies") or {}), **s.cookies.get_dict()}
    SPATH.write_text(json.dumps(S, ensure_ascii=False, indent=2))


def jdump(body, n=300):
    if isinstance(body.get("data"), dict) and isinstance(body["data"].get("list"), list):
        body = {**body, "data": {**body["data"], "list": f"<{len(body['data']['list'])} items>"}}
    return json.dumps(body, ensure_ascii=False)[:n]


def show_holes(s, label, **params):
    r = s.get(BASE + "/api/v3/hole/list", params=params, timeout=30)
    b = r.json()
    d = b.get("data", b)
    holes = d.get("list") or []
    print(f"\n[{label}] {params} -> {r.status_code} code={b.get('code')} "
          f"success={b.get('success')} total={d.get('total')} got={len(holes)}")
    first = None
    for h in holes[:8]:
        first = first or h.get("pid")
        txt = (h.get("text") or "").replace("\n", " ")[:55]
        print(f"   #{h.get('pid')}  reply={h.get('reply')}  like={h.get('likenum')}  text={txt!r}")
    return first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--code", default="")
    args = ap.parse_args()
    s, S = client()

    if args.send:
        r = s.post(BASE + "/api/jwt_send_msg", timeout=30)
        try:
            print("send_msg ->", r.status_code, jdump(r.json()))
        except Exception:
            print("send_msg ->", r.status_code, (r.text or "")[:200])
        save_cookies(s, S)
        return

    if args.code:
        r = s.post(BASE + "/api/jwt_msg_verify", data={"valid_code": args.code}, timeout=30)
        try:
            print("msg_verify ->", r.status_code, jdump(r.json()))
        except Exception:
            print("msg_verify ->", r.status_code, (r.text or "")[:200])
        save_cookies(s, S)

        # Prove content reads now work.
        pid = show_holes(s, "public timeline", page=1, limit=5)
        if pid:
            rc = s.get(BASE + "/api/v3/comment/list", params={"pid": pid, "page": 1, "limit": 5},
                       timeout=30)
            bc = rc.json()
            cmts = bc.get("data", bc).get("list") or []
            print(f"\n[comments of #{pid}] -> {rc.status_code} got={len(cmts)}")
            for c in cmts[:6]:
                txt = (c.get("text") or "").replace("\n", " ")[:65]
                print(f"   cid={c.get('cid')}  [{c.get('name_tag')}]  {txt!r}")
        show_holes(s, "关注 list", is_follow=1, page=1, limit=20)

        # Persistence poll: does the verified window survive past the ~2-min
        # no-uuid baseline now that we send the uuid header on every request?
        import time
        print("\n==== persistence poll (uuid header on) ====")
        t0 = time.time()
        duration, step, last_ok = 420, 25, 0
        while time.time() - t0 < duration:
            b = s.get(BASE + "/api/v3/hole/list",
                      params={"is_follow": 1, "page": 1, "limit": 3}, timeout=30).json()
            el = int(time.time() - t0)
            print(f"  t={el:3}s -> code={b.get('code')} success={b.get('success')}")
            if not b.get("success"):
                print(f"  >>> EXPIRED between {last_ok}s and {el}s")
                break
            last_ok = el
            time.sleep(step)
        else:
            print(f"  >>> still verified after ~{int(time.time() - t0)}s "
                  f"(vs ~120s no-uuid baseline) — uuid header extends the window")
        return

    ap.error("pass --send or --code <6-digit>")


if __name__ == "__main__":
    main()
