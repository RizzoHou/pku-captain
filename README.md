# plib-cli

A command-line client for **P-Lib** (PKUHUB, [pkuhub.cn](https://pkuhub.cn)) — search and download Peking University course materials (past exams, notes, study packs). Built primarily for [pku-captain](https://github.com/RizzoHou/pku-captain) agents to call as a subprocess, and usable directly by humans on the command line.

The mental model: **search by keyword → pick results → download by id.**

## Why a scraper

P-Lib is a server-rendered Flask site with **no public API**, and everything (search, material pages, downloads) is **login-gated**. So this client logs in with an email/password account, keeps a persistent cookie jar, scrapes the HTML, and downloads through the authenticated session. Auth is **self-healing**: any command that hits an expired session re-logs-in and retries, so you never have to run `login` first.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Exposes a `plib` console script (and `python -m plib_cli`).

## Credentials

Resolved in priority order:

1. `PLIB_EMAIL` / `PLIB_PASSWORD` environment variables.
2. `secrets/email` + `secrets/password` files (found by walking up from the working directory; **gitignored** — this is the dev-time source).
3. `~/.config/plib-cli/credentials/{email,password}`.

A P-Lib account is a self-registered email/password (not PKU IAAA). Register at [pkuhub.cn/register](https://pkuhub.cn/register).

## Usage

```bash
plib search "高等数学"                       # search all pages (JSON when piped, table in a terminal)
plib search "线性代数" --type 试卷 --sort downloads --limit 5
plib search "数据结构" --page 2 --time year  # one specific page only
plib show 727                                # full detail for one material
plib download 1544 -o ./materials            # download by id
plib download 1544 1571 1313                 # several at once
plib login                                   # force a fresh login (rarely needed)
plib quota                                    # downloads remaining today (from /profile)
```

Output format is **JSON when stdout is piped** (agent use) and a **human table** in an interactive terminal. Force either with `--format json|table` (works before or after the subcommand).

### Filters

- `--type` — one of `习题 其他 汇编 笔记 答案 试卷 课件 课本`
- `--time` — `all` (default) `week` `month` `year`
- `--sort` — `relevance` (default) `newest` `downloads` `views` `likes` `title` `comments`
- `--page` — by default `search` **auto-paginates** and returns every result (the site shows ~10 per page); pass `--page N` to fetch just one page
- `--limit` — cap the number of results returned (stops paginating early)

### Download quota

A normal account has a **10-downloads-per-day** server limit. The CLI reads the server's own remaining count from `/profile` (the `今日剩余下载次数` figure), refuses early with exit code 1 / `quota_exceeded` once it hits 0, and reports `quota_remaining` in every download response. Check it anytime with `plib quota`. Override the early guard with `--force` (the server still enforces its own cap). If `/profile` can't be read (transient network error or markup change), the guard fails open and the download proceeds — the server remains the backstop.

## JSON contract

Stable envelope on every command:

```json
{ "ok": true,  "data": { ... } }
{ "ok": false, "error": { "code": "quota_exceeded", "message": "..." } }
```

Exit codes: `0` success, `1` handled error (`PlibError`), `2` bad usage. Error `code` values: `no_credentials`, `auth_failed`, `not_found`, `quota_exceeded`, `network_error`, `parse_error`.

`search` → `{query, page, total, count, results:[{id, title, type, description, course, department, semester, uploader, date, downloads, views, favorites, url}]}`. `total` is the site's full result count; `count` is how many are in `results`. In the default auto-paginate mode `count` equals `total` (or `--limit`) and `page` is `1`; a `count` below `total` means the result was capped (by `--limit` or the page safety cap).
`show` → a material with the above plus `course_id, department_id, upload_time, file_type, files[], download_url`.
`download` → `{downloads:[{id, path, filename, bytes, quota_remaining}], quota_remaining}`. `quota` → `{download_remaining}`. Both `quota_remaining` and `download_remaining` are the server's `今日剩余下载次数`, or `null` if `/profile` couldn't be read.

## Use from pku-captain

The library is importable (`from plib_cli.client import PlibClient`), but the intended integration mirrors pku-captain's `pku3b` wrapper: run `plib` as a subprocess and `json.loads` its stdout.

```python
import json, subprocess

out = subprocess.run(
    ["plib", "search", "高等数学", "--limit", "10", "--format", "json"],
    capture_output=True, text=True, timeout=30,
)
payload = json.loads(out.stdout)
if payload["ok"]:
    for r in payload["data"]["results"]:
        ...  # r["id"], r["title"], r["downloads"], ...
```

## Development

```bash
pytest tests/        # parser tests pinned to saved fixtures + quota/credential tests
ruff check src tests
```

Parsers are pinned to real pages saved in `tests/fixtures/`. If P-Lib changes its markup, the tests fail loudly rather than returning silently-wrong data — re-capture the fixtures and adjust `parsers.py`.
