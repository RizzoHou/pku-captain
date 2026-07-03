# pypku3b

A pure-Python reimplementation of the **used subset** of
[`pku3b`](https://github.com/RizzoHou/pku3b) — the Rust "a Better BlackBoard for
PKUers" CLI. It talks to PKU's 教学网 (Blackboard) and 信息门户 directly over HTTP
so a host application can drive it **in-process**, with no external binary.

Built as a drop-in backend for [PKU Captain](https://github.com/RizzoHou/pku-captain),
mirroring how that project vendors its other Python CLI libraries (plib / dean /
treehole) and drives them in-process.

## Scope

Only the four surfaces PKU Captain actually consumes are ported:

| pku3b command | pypku3b |
|---|---|
| `assignment list [--all] [--all-term] --format json` | `Client.list_assignments()` |
| `announcement list` / `announcement show <id>` | `Client.list_announcements()` |
| `coursetable --raw [--otp-code]` | `Client.get_coursetable()` |
| `identity --format json` | `Client.get_identity()` |

Submission, downloads, video playback, grades, syllabus, and thesis search are
**not** ported.

## Library usage

```python
from pypku3b import Client

client = Client(secrets_dir="secrets/pku")   # reads secrets/pku/{id,password}
for a in client.list_assignments():
    print(a.deadline_iso, a.course_name, a.title)

identity = client.get_identity()
table = client.get_coursetable()
```

Credentials resolve from (1) `PKU_USERNAME`/`PKU_PASSWORD`, (2) an explicit
`secrets_dir`, or (3) `~/.config/pypku3b/{id,password}`. The session cookie jar
persists to `~/.cache/pypku3b/cookies.json` (override via `cookie_path`); pass
`seed_cookie_path=".../pku3b/ua.json"` to warm-start from an existing pku3b login.

## CLI

```bash
pypku3b assignment list --format json
pypku3b announcement list
pypku3b coursetable --raw
pypku3b identity --format json
```

The CLI exists mainly for standalone use and for diffing against the real
`pku3b`; the host app uses the library API.

## Authentication

Login goes through PKU's IAAA SSO, exactly like pku3b: three independent IAAA
apps (`blackboard`, `portalPublicQuery`, `portal2017`). If an account requires a
phone-token OTP, pass `otp_code=...`. Blackboard reuses a saved session when the
cookie jar is still valid (skipping re-login/OTP).

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # unit tests (offline; fixture-driven parsers)
ruff check src
```

Live, network-backed tests under `tests/live/` are skipped unless
`PYPKU3B_LIVE=1` (they need real PKU credentials).
