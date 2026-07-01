# pku-dean-cli

A small CLI for fetching **public** resources from the PKU Office of Educational Administration site, [dean.pku.edu.cn](https://dean.pku.edu.cn). Built to be used both by students directly and as a subprocess tool by [pku-captain](https://github.com/RizzoHou/pku-captain).

It mirrors the `plib` / `pku3b` convention pku-captain already consumes: a stable JSON envelope under a global `--format json` flag, plus human-readable output by default.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
dean --version
```

## Resources covered

All are public and need no login.

| Command | Source page | What it returns |
|---|---|---|
| `dean sidebar` | `index.php` 学生 sidebar | student links grouped by category |
| `dean guide <id>` | `student_info.php?id=` | content behind a sidebar link (sections + related links) |
| `dean rules list` | `rules_school.php` / `rules.php` | rules/regulations (school or national) |
| `dean rules show <id>` | `rules_info.php?id=` | full text of one rule |
| `dean download list` | `download.php` | downloadable files (forms, handbooks…) |
| `dean download get <id>` | `download_down.php?type=down` | download file(s) |
| `dean openinfo list` | `openinfo.php` | information-disclosure files |
| `dean openinfo get <id>` | `download_down.php?type=msg` | download disclosure file(s) |

## Usage

```bash
# Student sidebar, grouped by category
dean sidebar

# Content behind a sidebar link (id comes from the sidebar URL, e.g. ...?id=15 → 选课)
dean guide 15

# School rules — one page, or every page
dean rules list --scope school
dean rules list --scope school --all
dean rules list --scope national          # 国家/上级 documents (single page)

# Full text of a rule
dean rules show 20

# Downloadable files
dean download list --page 2
dean download list --all
dean download get 224 -o downloads        # saves into downloads/

# Information disclosure
dean openinfo list
dean openinfo get 17
```

Pagination: `--page N` for one page, `--all` to fetch every page (the last page is read from the site's page bar; a listing with no page bar is treated as a single page).

## JSON envelope (for programmatic callers)

Put `--format json` **before** the subcommand. Output goes to stdout, including on failure.

```bash
dean --format json download list
```

```json
{"ok": true, "data": {"page": 1, "last_page": 13, "count": 15, "items": [
  {"id": 224, "title": "2025-2026学年第二学期选课手册", "kind": "download",
   "download_url": "https://dean.pku.edu.cn/web/download_down.php?type=down&id=224",
   "downloads": 8517, "date": "2026-01-12"}
]}}
```

Errors carry a machine-readable `code`:

```json
{"ok": false, "error": {"code": "not_found", "message": "no rule found with id=99999999"}}
```

Codes: `not_found`, `timeout`, `network_error`, `http_error`, `parse_error`, `bad_argument`, `io_error`. The process exits non-zero on error.

## Library use

The same logic is importable, so pku-captain can call it in-process instead of via subprocess:

```python
from dean import DeanClient
from dean import resources

client = DeanClient()
for item in resources.list_all_files(client, "download"):
    print(item.id, item.title)
```

## Authentication

Every resource above is public. The only dean content behind PKU's central IAAA login (`iaaa.pku.edu.cn`) is the separate `service/` portal (course selection, room booking, grade queries), which is **not** implemented. `dean/auth.py` holds the credential-loading hook (`secrets/id`, `secrets/password`) for when that scope is added.

`secrets/` is gitignored — never commit real credentials.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest      # offline; uses saved HTML fixtures
.venv/bin/ruff check src tests
```

## License

[MIT](LICENSE)
