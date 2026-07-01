# pku-treehole

> Unofficial. Personal-use tooling for your **own** account — not affiliated with, endorsed by, or supported by Peking University. Use at your own risk.

Monitor updates to your **关注 (followed) holes** on [PKU Treehole](https://treehole.pku.edu.cn). The platform never notifies you when a followed hole gets new replies, so this polls the 关注 list, diffs reply counts, and shows the new replies themselves.

Built primarily as a Python **library** for a companion PKU-student agent; the CLI is for standalone / cron use.

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Auth model (read before using)

PKU's IAAA SSO fronts treehole. Two things gate access — both documented in `docs/treehole-protocol.md`:

1. **Login** (`treehole login`) runs the IAAA password flow and caches a ~30-day JWT to `secrets/session.json`. It **consumes one attempt toward the E21 30-minute lockout** — never script it in a retry loop.
2. **SMS verification** — content reads return `code 40002` until the device identity is SMS-verified. Run `treehole verify --send` then `treehole verify --code <4-digit>`. Verification binds to a stable device `uuid` and survives as long as a browser session; reads need only `JWT + uuid` (cookies are not required).

`secrets/` (gitignored) holds `id`, `password`, and the cached `session.json`.

## CLI

```bash
treehole login              # IAAA login → cache session  (consumes one E21 attempt!)
treehole verify --send      # SMS to the bound phone
treehole verify --code 1234
treehole whoami
treehole followed           # list followed holes + reply counts
treehole monitor            # one diff against state.json — holes that gained replies, with the new comment text
treehole monitor --no-comments  # count deltas only (skips the extra per-hole comment fetch)
treehole monitor --watch 300  # poll every ~300s (±20% jitter)
treehole monitor --holes 123,456        # watch only these pids (fetched directly via hole/get — gentler)
treehole monitor --holes-file watch.txt  # …or read pids from a file (one per line, # comments)
treehole monitor --notify   # post macOS desktop notifications for each update (macOS only)
```

`--json` works on every command. `monitor` **fails loud**: on `40002` it exits non-zero with "needs SMS re-verification" rather than returning an empty "all caught up".

A **watchlist** (`--holes` / `--holes-file`) narrows monitoring to a chosen subset. Those holes are fetched one-by-one via `hole/get` instead of paging the whole 关注 list, which is much gentler at a tight poll interval — and the watchlist run *merges* state, so it never clobbers your full-follow-list `state.json` and a transiently-unreachable hole keeps its baseline.

## macOS notifications (daemon)

Run the monitor as a background LaunchAgent that posts a desktop notification whenever a watched hole gets new replies:

```bash
macos/install-agent.sh --interval 60 --holes 123,456   # poll every 60s, watch two holes
macos/install-agent.sh --interval 300                  # …or watch ALL followed holes, every 5 min
macos/uninstall-agent.sh                               # remove
```

Notes:
- **Interval** is arbitrary (`--interval SECONDS`, default 60). The agent runs single-shot per tick (launchd `StartInterval`), so a session that needs SMS re-verification never restart-storms; it just posts one rate-limited "需要重新短信验证" banner.
- **Watchlist** lives at `secrets/watchlist` (one pid per line). Edit it and `launchctl kickstart gui/$(id -u)/com.pku.treehole.notify` to reload. Omit `--holes` with no existing watchlist to watch every followed hole.
- **Notifications** use `osascript` (`display notification`, built-in). The agent loads into the `gui/<uid>` domain so banners reach your desktop session — a process started over plain SSH cannot post them. The **first** banner may be suppressed until you allow notifications for the posting app ("Script Editor") in System Settings → Notifications. terminal-notifier is intentionally **not** used: on macOS 26 Apple removed its delivery API, so it returns success but shows nothing — do not install it. Because `osascript` cannot set a custom icon or a click-to-open URL, neither is offered.
- Logs: `logs/notify.{out,err}.log`.

## Library

```python
from treehole.app import build_client, build_monitor

client = build_client("secrets")          # cached session + transparent re-login on 401
holes = client.followed_all()             # [{pid, reply, likenum, text, ...}, ...]

mon = build_monitor("secrets", state_path="state.json")
for u in mon.check():                      # only holes whose reply count grew
    print(u.pid, u.old_reply, "->", u.new_reply)
    for c in u.new_comments:               # the new replies (cid, text, name_tag, timestamp)
        print("  ", c.name_tag, c.text)
# mon.check(fetch_comments=False) skips the comment fetch (count deltas only).
# mon.check(only={"123", "456"}) watches just those pids (fetched via hole/get; state is merged).
```

State is minimal by design — `pid -> {reply, last_cid, checked_at}`, where `last_cid` is the id cursor used to fetch only the new replies. Never stores comment text.

## Develop

```bash
.venv/bin/pytest                          # diff + client-contract tests (no network)
find src -name '*.py' -print0 | xargs -0 .venv/bin/python -m py_compile
```
