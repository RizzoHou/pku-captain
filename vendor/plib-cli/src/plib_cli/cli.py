"""``plib`` command-line entry point.

Subcommands: ``search``, ``show``, ``download``, ``login``. Output is JSON by
default when stdout is not a TTY (so pku-captain's Tool wrapper parses it like
``pku3b --format json``); when run interactively it defaults to a human table.
Override either way with ``--format json|table``.

JSON envelope is stable:
    {"ok": true,  "data": {...}}
    {"ok": false, "error": {"code": "...", "message": "..."}}
Exit code is 0 on success, 1 on a handled PlibError, 2 on bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import PlibClient
from .errors import PlibError
from .models import Material, SearchPage

# Values mirror P-Lib's own filter <select> option values (verified against
# tests/fixtures/search.html), so they pass straight through to the query.
TYPE_CHOICES = ["习题", "其他", "汇编", "笔记", "答案", "试卷", "课件", "课本"]
TIME_CHOICES = {"all": "", "week": "week", "month": "month", "year": "year"}
SORT_CHOICES = ["relevance", "newest", "downloads", "views", "likes", "title", "comments"]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    fmt = getattr(args, "format", "auto")
    base_url = getattr(args, "base_url", None)
    as_json = fmt == "json" or (fmt == "auto" and not sys.stdout.isatty())
    try:
        client = PlibClient(base_url=base_url)
        data = args.handler(client, args)
    except PlibError as exc:
        _emit_error(exc, as_json)
        return 1
    _emit(data, as_json, args)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    # Global flags live in a parent parser with SUPPRESS defaults so they work
    # both before and after the subcommand (e.g. `plib search x --format json`)
    # without a later empty subparser pass clobbering an earlier value.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--format",
        choices=["auto", "json", "table"],
        default=argparse.SUPPRESS,
        help="output format (default: json when piped, table when interactive)",
    )
    common.add_argument(
        "--base-url",
        default=argparse.SUPPRESS,
        help="override the P-Lib base URL (debug/testing)",
    )

    parser = argparse.ArgumentParser(
        prog="plib",
        description="Search and download PKU course materials from P-Lib (pkuhub.cn).",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("search", help="search materials by keyword", parents=[common])
    s.add_argument("query", help="search keywords")
    s.add_argument("--type", choices=TYPE_CHOICES, help="filter by material type")
    s.add_argument(
        "--time",
        choices=list(TIME_CHOICES),
        default="all",
        help="filter by recency (default: all)",
    )
    s.add_argument(
        "--sort", choices=SORT_CHOICES, default="relevance", help="result ordering"
    )
    s.add_argument(
        "--page",
        type=int,
        default=None,
        help="fetch only this single page (default: auto-paginate all pages)",
    )
    s.add_argument(
        "--limit", type=int, default=None, help="cap the number of results shown"
    )
    s.set_defaults(handler=_cmd_search)

    sh = sub.add_parser(
        "show", help="show full detail for one material", parents=[common]
    )
    sh.add_argument("id", type=int, help="material id")
    sh.set_defaults(handler=_cmd_show)

    d = sub.add_parser(
        "download",
        help="download one or more materials (10/day quota)",
        parents=[common],
    )
    d.add_argument("ids", type=int, nargs="+", help="material id(s) to download")
    d.add_argument("-o", "--output", default=".", help="destination directory")
    d.add_argument(
        "--force",
        action="store_true",
        help="ignore the server-reported remaining-quota guard",
    )
    d.set_defaults(handler=_cmd_download)

    lg = sub.add_parser(
        "login", help="log in and cache the session", parents=[common]
    )
    lg.set_defaults(handler=_cmd_login)

    q = sub.add_parser(
        "quota", help="show downloads remaining today (from /profile)", parents=[common]
    )
    q.set_defaults(handler=_cmd_quota)

    return parser


# -- command handlers ----------------------------------------------------


def _cmd_search(client: PlibClient, args) -> SearchPage:
    # No --page → auto-paginate the whole result set (the default); an explicit
    # --page fetches just that one page.
    if args.page is None:
        return client.search_all(
            args.query,
            type=args.type,
            time=TIME_CHOICES[args.time],
            sort=args.sort,
            limit=args.limit,
        )
    page = client.search(
        args.query,
        type=args.type,
        time=TIME_CHOICES[args.time],
        sort=args.sort,
        page=args.page,
    )
    if args.limit is not None:
        page.results = page.results[: args.limit]
    return page


def _cmd_show(client: PlibClient, args) -> Material:
    return client.material(args.id)


def _cmd_download(client: PlibClient, args) -> dict:
    results = []
    for mid in args.ids:
        results.append(client.download(mid, args.output, force=args.force).to_dict())
    return {"downloads": results, "quota_remaining": client.quota_remaining()}


def _cmd_login(client: PlibClient, args) -> dict:
    client.login()
    return {"status": "logged_in", "quota_remaining": client.quota_remaining()}


def _cmd_quota(client: PlibClient, args) -> dict:
    return client.profile().to_dict()


# -- output --------------------------------------------------------------


def _emit(data, as_json: bool, args) -> None:
    if as_json:
        payload = data.to_dict() if hasattr(data, "to_dict") else data
        print(json.dumps({"ok": True, "data": payload}, ensure_ascii=False, indent=2))
        return
    if args.command == "search":
        _print_search_table(data, args)
    elif args.command == "show":
        _print_material(data)
    elif args.command == "quota":
        _print_quota(data)
    elif args.command == "login":
        _print_login(data)
    elif args.command == "download":
        _print_download(data)
    else:
        # Fallback so a future subcommand degrades to JSON rather than crashing.
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _emit_error(exc: PlibError, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": str(exc)}},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"error ({exc.code}): {exc}", file=sys.stderr)


def _print_search_table(page: SearchPage, args) -> None:
    total = page.total if page.total is not None else "?"
    # In aggregate mode (no --page) the line is just "N of total"; when a single
    # page was explicitly requested, name it.
    if getattr(args, "page", None) is not None:
        header = f'"{page.query}" — page {page.page}, {len(page.results)} of {total}'
    else:
        header = f'"{page.query}" — {len(page.results)} of {total} results'
    print(header)
    for r in page.results:
        meta = " · ".join(x for x in (r.type, r.course, r.semester) if x)
        print(f"  [{r.id}] {r.title}")
        if meta:
            print(f"        {meta}")
        print(
            f"        ↓{r.downloads or 0} 👁{r.views or 0} · {r.uploader or '?'} · {r.date or '?'}"
        )


def _print_material(m: Material) -> None:
    print(f"[{m.id}] {m.title}")
    rows = [
        ("type", m.type),
        ("course", m.course),
        ("department", m.department),
        ("semester", m.semester),
        ("uploader", m.uploader),
        ("uploaded", m.upload_time),
        ("downloads", m.downloads),
        ("views", m.views),
        ("file type", m.file_type),
    ]
    for label, value in rows:
        if value is not None:
            print(f"  {label:11} {value}")
    if m.description:
        print(f"  description {m.description}")
    if m.files:
        print(f"  files       {len(m.files)}: " + ", ".join(m.files[:8]))
    print(f"  download    {m.download_url}")


def _fmt_remaining(n: int | None) -> str:
    return "unknown" if n is None else str(n)


def _human_size(n: int | None) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _print_quota(data: dict) -> None:
    print(f"downloads remaining today: {_fmt_remaining(data.get('download_remaining'))}")


def _print_login(data: dict) -> None:
    print(f"logged in · {_fmt_remaining(data.get('quota_remaining'))} downloads remaining today")


def _print_download(data: dict) -> None:
    for d in data.get("downloads", []):
        size = _human_size(d.get("bytes"))
        print(f"[{d['id']}] {d['filename']} → {d['path']} ({size})")
    print(f"  {_fmt_remaining(data.get('quota_remaining'))} downloads remaining today")


if __name__ == "__main__":
    sys.exit(main())
