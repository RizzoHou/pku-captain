"""Command-line veneer. The library (TreeholeClient / Monitor) is the real
product; this is for standalone / cron use. `--json` on every command.

    python -m treehole login            # IAAA login (consumes one E21 attempt!)
    python -m treehole verify --send    # SMS to bound phone
    python -m treehole verify --code 1234
    python -m treehole whoami
    python -m treehole groups
    python -m treehole followed
    python -m treehole search 考试      # holes whose text contains the keyword
    python -m treehole fetch 123456     # original post + full comment history
    python -m treehole monitor          # one diff; shows new replies by default
    python -m treehole monitor --no-comments  # count deltas only (lighter)
    python -m treehole monitor --watch 300    # poll every ~300s with jitter
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .app import build_client, build_monitor
from .auth import Credentials, login
from .errors import APIError, AuthError, NeedSMSVerification, TreeholeError
from .session import SessionStore


def _out(obj, as_json: bool, human) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        human(obj)


def _trim(text: str | None, n: int = 55) -> str:
    return (text or "").replace("\n", " ")[:n]


# treehole timestamps are unix seconds; render in Beijing time (the UI's frame)
# regardless of where the CLI runs (the daemon box / CI may be UTC).
_BEIJING = timezone(timedelta(hours=8))


def _fmt_time(ts) -> str:
    """Unix seconds -> 'YYYY-MM-DD HH:MM:SS' in Beijing time; '?' on missing/bad input."""
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(int(ts), _BEIJING).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, TypeError):
        return "?"


def _print_hole_line(h, *, indent: str = "  ") -> None:
    """One-line hole summary (pid + time + counts + trimmed text). Shared by followed/search."""
    print(f"{indent}#{h.get('pid')}  {_fmt_time(h.get('timestamp'))}  "
          f"reply={h.get('reply')}  like={h.get('likenum')}  {_trim(h.get('text'))!r}")


def _print_comment_line(c, *, indent: str = "  ") -> None:
    """One comment (time + name tag + full text, with the quoted reply if any). Used by fetch.
    Takes a raw comment dict; the monitor renders its own Comment objects."""
    quote = c.get("quote") if isinstance(c.get("quote"), dict) else None
    qhint = f"(↩ {_trim(quote.get('text'), 20)!r}) " if quote and quote.get("text") else ""
    print(f"{indent}{_fmt_time(c.get('timestamp'))}  [{c.get('name_tag')}] "
          f"{qhint}{(c.get('text') or '').rstrip()}")


def cmd_login(a) -> int:
    store = SessionStore(a.session or f"{a.secrets_dir}/session.json")
    existing = store.load_or_none()
    login_uuid = None if a.new_uuid else (existing.login_uuid if existing else None)
    print("⚠ IAAA login consumes one attempt toward the E21 30-min lockout.",
          file=sys.stderr)
    ident = login(Credentials.from_dir(a.secrets_dir), login_uuid=login_uuid, otp=a.otp)
    store.save(ident)
    _out({"uid": ident.uid, "login_uuid": ident.login_uuid, "expires_in": ident.expires_in},
         a.json, lambda d: print(f"logged in: uid={d['uid']} uuid={d['login_uuid']} "
                                 f"exp={d['expires_in']}\nsaved -> {store.path}"))
    print("note: a fresh JWT may still need SMS re-verification "
          "(`verify --send` then `--code`).", file=sys.stderr)
    return 0


def cmd_verify(a) -> int:
    client = build_client(a.secrets_dir, session_path=a.session)
    if a.send:
        client.send_sms()
        print("SMS sent to the bound phone. Re-run with --code <4-digit>.")
        return 0
    if a.code:
        client.verify_sms(a.code)
        print("verified. content reads should now work.")
        return 0
    print("pass --send or --code <4-digit>", file=sys.stderr)
    return 2


def cmd_whoami(a) -> int:
    me = build_client(a.secrets_dir, session_path=a.session).users_info()
    _out(me, a.json, lambda m: print(f"{m.get('uid')}  {m.get('name')}  "
                                     f"{m.get('department')}  newmsg={m.get('newmsgcount')}"))
    return 0


def cmd_groups(a) -> int:
    groups = build_client(a.secrets_dir, session_path=a.session).bookmarks()
    def human(gs):
        if not gs:
            print("no named 关注 groups (all ungrouped)")
        for g in gs:
            print(f"  id={g.get('id')}  {g.get('bookmark_name')}  holes={g.get('hole_count')}")
    _out(groups, a.json, human)
    return 0


def cmd_followed(a) -> int:
    holes = build_client(a.secrets_dir, session_path=a.session).followed_all(limit=a.limit)
    def human(hs):
        print(f"{len(hs)} followed holes")
        for h in hs:
            _print_hole_line(h)
    _out(holes, a.json, human)
    return 0


def cmd_search(a) -> int:
    client = build_client(a.secrets_dir, session_path=a.session)
    if a.all:
        holes = client.search_all(a.keyword, limit=a.limit)
    else:
        holes = client.search(a.keyword, limit=a.limit).get("list") or []
    def human(hs):
        print(f"{len(hs)} result(s) for {a.keyword!r}")
        for h in hs:
            _print_hole_line(h)
    _out(holes, a.json, human)
    return 0


def cmd_fetch(a) -> int:
    client = build_client(a.secrets_dir, session_path=a.session)
    hole = client.hole(a.pid)
    comments = client.comments_all(a.pid, limit=a.limit)
    if a.json:
        print(json.dumps({"hole": hole, "comments": comments}, ensure_ascii=False, indent=2))
        return 0
    print(f"#{hole.get('pid')}  {_fmt_time(hole.get('timestamp'))}  "
          f"reply={hole.get('reply')}  like={hole.get('likenum')}")
    print(hole.get("text") or "")
    print(f"--- {len(comments)} comment(s) ---")
    for c in comments:
        _print_comment_line(c)
    return 0


def _print_updates(updates) -> None:
    if not updates:
        print("no updates")
        return
    print(f"{len(updates)} update(s):")
    for u in updates:
        print(f"  #{u.pid}  +{u.delta} replies ({u.old_reply} -> {u.new_reply})  "
              f"{_trim(u.text)!r}")
        for c in u.new_comments:
            print(f"      ↳ [{c.name_tag}] {_trim(c.text, 70)!r}")
        hidden = u.delta - len(u.new_comments)
        if u.new_comments and hidden > 0:
            print(f"      … +{hidden} more new repl{'y' if hidden == 1 else 'ies'} not shown")


def _parse_watchlist(holes_arg: str, holes_file: str) -> set[str] | None:
    """Collect pids from --holes (comma-separated) and --holes-file (one per line,
    `#` starts a comment). Returns None when neither is given (= watch all)."""
    pids: set[str] = set()
    if holes_arg:
        pids.update(p.strip() for p in holes_arg.split(",") if p.strip())
    if holes_file:
        path = Path(holes_file)
        if not path.exists():
            raise TreeholeError(f"watchlist file not found: {holes_file}")
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                pids.add(line)
    return pids or None


def _make_notifier(state_path: str):
    from .notify import MacNotifier
    return MacNotifier(state_path=f"{state_path}.notify.json")


def cmd_monitor(a) -> int:
    only = _parse_watchlist(a.holes, a.holes_file)
    mon = build_monitor(a.secrets_dir, session_path=a.session, state_path=a.state)
    fetch_comments = not a.no_comments
    notifier = None
    if a.notify:
        try:
            notifier = _make_notifier(a.state)
        except RuntimeError as e:
            print(f"--notify unavailable: {e}", file=sys.stderr)
            return 2

    def poll_and_report(stamp: str | None = None):
        updates = mon.check(only=only, fetch_comments=fetch_comments)
        if a.json:
            if stamp:
                print(json.dumps({"at": stamp, "updates": [u.to_dict() for u in updates]},
                                 ensure_ascii=False))
            else:
                print(json.dumps([u.to_dict() for u in updates], ensure_ascii=False, indent=2))
        else:
            if stamp:
                print(f"[{stamp}] ", end="")
            _print_updates(updates)
        if notifier:
            for u in updates:
                notifier.notify_update(u)
        return updates

    if not a.watch:
        try:
            poll_and_report()
        except (NeedSMSVerification, AuthError) as e:
            if notifier:
                notifier.notify_auth_needed(str(e))
            raise  # main() reports + sets the exit code
        return 0
    # Watch loop: poll every ~interval with ±20% jitter (gentle, single account).
    # Survive transient network/API hiccups (log + keep polling); exit only on
    # failures a poll can't self-heal (SMS re-verification, broken auth).
    import random
    print(f"watching every ~{a.watch}s (Ctrl-C to stop)", file=sys.stderr)
    while True:
        try:
            poll_and_report(time.strftime("%H:%M:%S"))
        except NeedSMSVerification as e:
            if notifier:
                notifier.notify_auth_needed(str(e))
            print(f"needs SMS re-verification: {e}", file=sys.stderr)
            return 3
        except AuthError as e:  # can't self-heal in an unattended loop
            if notifier:
                notifier.notify_auth_needed(str(e))
            print(f"auth failed, stopping: {e}", file=sys.stderr)
            return 2
        except (requests.exceptions.RequestException, APIError) as e:
            print(f"[{time.strftime('%H:%M:%S')}] transient error, retrying next tick: {e}",
                  file=sys.stderr)
        sys.stdout.flush()
        time.sleep(a.watch * (0.8 + 0.4 * random.random()))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="treehole", description="monitor PKU Treehole 关注 holes")
    p.add_argument("--secrets-dir", dest="secrets_dir", default="secrets")
    p.add_argument("--session", default=None, help="session.json path (default <secrets>/session.json)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="IAAA login (consumes one E21 attempt)")
    sp.add_argument("--otp", default="", help="IAAA mobile OTP, if ever required")
    sp.add_argument("--new-uuid", action="store_true", help="force a fresh device id")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("verify", help="SMS verification gate")
    sp.add_argument("--send", action="store_true")
    sp.add_argument("--code", default="")
    sp.set_defaults(func=cmd_verify)

    sub.add_parser("whoami", help="account info").set_defaults(func=cmd_whoami)
    sub.add_parser("groups", help="关注 groups").set_defaults(func=cmd_groups)

    sp = sub.add_parser("followed", help="list followed holes")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_followed)

    sp = sub.add_parser("search", help="search holes by keyword")
    sp.add_argument("keyword")
    sp.add_argument("--limit", type=int, default=25, help="results per page")
    sp.add_argument("--all", action="store_true", help="paginate all results (capped)")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="full comment history of one hole by pid")
    sp.add_argument("pid")
    sp.add_argument("--limit", type=int, default=50, help="comments fetched per page")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("monitor", help="diff followed holes against state, show new replies")
    sp.add_argument("--state", default="state.json")
    sp.add_argument("--watch", type=int, default=0, help="poll interval seconds (0 = once)")
    sp.add_argument("--no-comments", action="store_true",
                    help="only show reply-count deltas; skip fetching new comment text (lighter)")
    sp.add_argument("--holes", default="",
                    help="watch only these pids (comma-separated); fetched directly, gentler")
    sp.add_argument("--holes-file", dest="holes_file", default="",
                    help="file of pids to watch, one per line (# comments allowed)")
    sp.add_argument("--notify", action="store_true",
                    help="post macOS desktop notifications for each update (macOS only)")
    sp.set_defaults(func=cmd_monitor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NeedSMSVerification as e:
        print(f"needs SMS re-verification (run `verify --send` then `--code`): {e}",
              file=sys.stderr)
        return 3
    except TreeholeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
