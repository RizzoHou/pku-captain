"""Command-line interface for pku-dean-cli.

Global ``--format json`` (placed before the subcommand, matching the plib/pku3b
convention) switches output to the stable JSON envelope. Without it, output is
human-readable text.

    dean sidebar
    dean rules list --scope school --all
    dean rules show 20
    dean notice list --page 2
    dean notice show 743
    dean download list --page 2
    dean download get 213 -o downloads
    dean openinfo list
    dean openinfo get 17
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, resources
from .client import DeanClient
from .errors import DeanError
from .output import (
    emit_json_error,
    emit_json_ok,
    jsonable,
    render_file_list,
    render_files,
    render_guide,
    render_notice_doc,
    render_notice_list,
    render_notices,
    render_rule_doc,
    render_rule_list,
    render_rules,
    render_sidebar,
)

DEFAULT_OUTPUT_DIR = "downloads"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dean",
        description="Fetch public resources from dean.pku.edu.cn.",
    )
    parser.add_argument("--version", action="version", version=f"dean {__version__}")
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human). 'json' emits a stable envelope.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sidebar
    sub.add_parser("sidebar", help="List the 学生 sidebar links by category.")

    # guide (content behind a student_info.php sidebar link)
    guide = sub.add_parser("guide", help="Show a student guide page (student_info.php).")
    guide.add_argument("id", type=int, help="Guide id (student_info.php?id=).")

    # rules
    rules = sub.add_parser("rules", help="Browse rules/regulations.")
    rules_sub = rules.add_subparsers(dest="action", required=True)
    rules_list = rules_sub.add_parser("list", help="List rules.")
    rules_list.add_argument(
        "--scope",
        choices=["school", "national"],
        default="school",
        help="school = 北大校级 (rules_school.php), national = 国家/上级 (rules.php).",
    )
    _add_paging(rules_list)
    rules_show = rules_sub.add_parser("show", help="Show full text of one rule.")
    rules_show.add_argument("id", type=int, help="Rule id (rules_info.php?id=).")

    # notices
    notice = sub.add_parser("notice", help="Browse notices/announcements (notice.php).")
    notice_sub = notice.add_subparsers(dest="action", required=True)
    notice_list = notice_sub.add_parser("list", help="List notices.")
    _add_paging(notice_list)
    notice_show = notice_sub.add_parser("show", help="Show full text of one notice.")
    notice_show.add_argument("id", type=int, help="Notice id (notice_details.php?id=).")

    # download / openinfo share the same shape
    for name, helptext in (
        ("download", "Browse downloadable files (download.php)."),
        ("openinfo", "Browse information-disclosure files (openinfo.php)."),
    ):
        res = sub.add_parser(name, help=helptext)
        res_sub = res.add_subparsers(dest="action", required=True)
        res_list = res_sub.add_parser("list", help="List files.")
        _add_paging(res_list)
        res_get = res_sub.add_parser("get", help="Download file(s) by id.")
        res_get.add_argument("id", type=int, nargs="+", help="File id(s).")
        res_get.add_argument(
            "-o", "--out", default=None, help=f"Output dir (default: {DEFAULT_OUTPUT_DIR}/<kind>)."
        )

    return parser


def _add_paging(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--page", type=int, default=1, help="Page number (default 1).")
    group.add_argument("--all", action="store_true", help="Fetch all pages.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = DeanClient(timeout=args.timeout)
    try:
        data, human = _dispatch(client, args)
    except DeanError as exc:
        if args.format == "json":
            emit_json_error(exc)
        else:
            print(f"error[{exc.code}]: {exc.message}", file=sys.stderr)
        return 1

    if args.format == "json":
        emit_json_ok(data)
    else:
        print(human)
    return 0


def _dispatch(client: DeanClient, args: argparse.Namespace):
    """Run the selected command; return ``(jsonable_data, human_text)``."""
    cmd = args.command
    if cmd == "sidebar":
        links = resources.get_sidebar(client)
        return jsonable(links), render_sidebar(links)

    if cmd == "guide":
        doc = resources.show_guide(client, args.id)
        return jsonable(doc), render_guide(doc)

    if cmd == "rules":
        if args.action == "show":
            doc = resources.show_rule(client, args.id)
            return jsonable(doc), render_rule_doc(doc)
        if args.all:
            items = resources.list_all_rules(client, args.scope)
            return _all_payload(items), render_rule_list(items)
        page = resources.list_rules(client, args.scope, page=args.page)
        return jsonable(page), render_rules(page)

    if cmd == "notice":
        if args.action == "show":
            doc = resources.show_notice(client, args.id)
            return jsonable(doc), render_notice_doc(doc)
        if args.all:
            items = resources.list_all_notices(client)
            return _all_payload(items), render_notice_list(items)
        page = resources.list_notices(client, page=args.page)
        return jsonable(page), render_notices(page)

    if cmd in ("download", "openinfo"):
        if args.action == "get":
            out_dir = args.out or f"{DEFAULT_OUTPUT_DIR}/{cmd}"
            saved = [
                str(resources.download_file(client, cmd, fid, out_dir)) for fid in args.id
            ]
            data = {"saved": saved, "count": len(saved)}
            human = "saved:\n" + "\n".join(f"  {p}" for p in saved)
            return data, human
        if args.all:
            items = resources.list_all_files(client, cmd)
            return _all_payload(items), render_file_list(items)
        page = resources.list_files(client, cmd, page=args.page)
        return jsonable(page), render_files(page)

    raise DeanError(f"unknown command: {cmd}", code="bad_argument")  # pragma: no cover


def _all_payload(items: list):
    return {"all_pages": True, "count": len(items), "items": jsonable(items)}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
