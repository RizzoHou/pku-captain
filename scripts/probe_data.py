"""Reuse the cached JWT session to fetch real treehole data (read-only).

Proves the client pulls actual content: public timeline, one hole's
comments, whoami, and the (currently empty) 关注 list. Hits only
treehole.pku.edu.cn (reliable) — no IAAA round-trip.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://treehole.pku.edu.cn/chapi"
SESSION = json.loads((ROOT / "secrets" / "session.json").read_text())


def client() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
        "Authorization": f"Bearer {SESSION['jwt']}",
        "Accept": "application/json",
    })
    for k, v in (SESSION.get("cookies") or {}).items():
        s.cookies.set(k, v)
    return s


def get(s, path, **params):
    r = s.get(BASE + path, params=params or None, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": (r.text or "")[:200]}


def post(s, path, **data):
    r = s.post(BASE + path, data=data or None, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": (r.text or "")[:200]}


def holes_of(payload):
    d = payload.get("data", payload)
    return d.get("list") or [], d.get("total")


def main():
    s = client()

    print("==== whoami (POST users/info) ====")
    code, body = post(s, "/api/v3/users/info")
    info = body.get("data", body)
    print(f"  status {code}  success={body.get('success')}")
    if isinstance(info, dict):
        print(f"  uid={info.get('uid') or info.get('user_id')}  "
              f"name_tag={info.get('name_tag')}  fields={list(info)[:12]}")

    print("\n==== public timeline (hole/list, first 5) ====")
    code, body = get(s, "/api/v3/hole/list", page=1, limit=5)
    holes, total = holes_of(body)
    print(f"  status {code}  success={body.get('success')}  total={total}  got={len(holes)}")
    first_pid = None
    for h in holes:
        first_pid = first_pid or h.get("pid")
        txt = (h.get("text") or "").replace("\n", " ")[:60]
        print(f"   #{h.get('pid')}  reply={h.get('reply')}  like={h.get('likenum')}  "
              f"tag={h.get('tag')}  text={txt!r}")

    if first_pid:
        print(f"\n==== comments of #{first_pid} (comment/list, first 5) ====")
        code, body = get(s, "/api/v3/comment/list", pid=first_pid, page=1, limit=5)
        cmts, total = holes_of(body)
        print(f"  status {code}  success={body.get('success')}  total={total}  got={len(cmts)}")
        for c in cmts:
            txt = (c.get("text") or "").replace("\n", " ")[:70]
            print(f"   cid={c.get('cid')}  [{c.get('name_tag')}]  {txt!r}")

    print("\n==== 关注 groups (bookmark/list) ====")
    code, body = get(s, "/api/v3/bookmark/list", page=1, limit=30)
    groups, total = holes_of(body)
    print(f"  status {code}  total={total}  groups={[g.get('bookmark_name') for g in groups]}")

    print("\n==== 关注 holes (hole/list?is_follow=1) ====")
    code, body = get(s, "/api/v3/hole/list", is_follow=1, page=1, limit=20)
    holes, total = holes_of(body)
    print(f"  status {code}  total={total}  got={len(holes)}")
    for h in holes[:10]:
        txt = (h.get("text") or "").replace("\n", " ")[:50]
        print(f"   #{h.get('pid')}  reply={h.get('reply')}  text={txt!r}")


if __name__ == "__main__":
    main()
