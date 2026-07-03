"""Standalone CLI mirroring the used pku3b commands.

Primarily for standalone use and for diffing against the real pku3b's output;
the host app (pku-captain) drives :class:`~pypku3b.client.Client` in-process
rather than this CLI. Output formats match pku3b where a machine format exists
(``assignment list --format json``, ``identity --format json``, ``coursetable
--raw``); the human-readable announcement text is ANSI-free.
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import Client
from .errors import Pku3bError


def _build_client(args: argparse.Namespace) -> Client:
    return Client(
        secrets_dir=args.secrets_dir,
        cookie_path=args.cookie_path,
        seed_cookie_path=args.seed_cookies,
    )


def _print_json(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _cmd_assignment_list(args: argparse.Namespace) -> int:
    client = _build_client(args)
    assignments = client.list_assignments(
        include_completed=args.all,
        all_term=args.all_term,
        force=args.force,
        otp_code=args.otp_code,
    )
    if args.format == "json":
        _print_json([a.to_dict() for a in assignments])
    else:
        title = "所有作业 (包括已完成)" if (args.all or args.all_term) else "未完成作业"
        lines = [f"> {title} ({len(assignments)}) <", ""]
        for a in assignments:
            state = f"已完成: {a.last_attempt}" if a.completed else (a.deadline_raw or "无截止时间")
            lines.append(f"{a.course_name} > {a.title} ({state}) {a.id}")
        sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _cmd_announcement_list(args: argparse.Namespace) -> int:
    client = _build_client(args)
    announcements = client.list_announcements(
        all_term=args.all_term, force=args.force, otp_code=args.otp_code
    )
    lines = [f"> 课程公告 ({len(announcements)}) <", ""]
    for a in announcements:
        suffix = f" ({len(a.attachments)} 个附件)" if a.attachments else ""
        lines.append(f"[{a.index:>2}] {a.course} > {a.title}{suffix} {a.id}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _cmd_announcement_show(args: argparse.Namespace) -> int:
    client = _build_client(args)
    announcements = client.list_announcements(
        all_term=args.all_term, force=args.force
    )
    match = next((a for a in announcements if a.id == args.id), None)
    if match is None:
        sys.stderr.write(f"announcement with id {args.id} not found\n")
        return 1
    out = ["> 公告详情 <", "", f"{match.course} > {match.title}", f"ID: {match.id}"]
    if match.posted_time:
        out.append(f"发布时间: {match.posted_time}")
    if match.descriptions:
        out.append("")
        out.extend(match.descriptions)
    if match.attachments:
        out.append("")
        out.extend(f"[附件] {att.name}" for att in match.attachments)
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def _cmd_coursetable(args: argparse.Namespace) -> int:
    client = _build_client(args)
    table = client.get_coursetable(force=args.force, otp_code=args.otp_code)
    if args.raw:
        sys.stdout.write(json.dumps(table.raw, ensure_ascii=False) + "\n")
    else:
        _print_json(table.to_dict())
    return 0


def _cmd_identity(args: argparse.Namespace) -> int:
    client = _build_client(args)
    identity = client.get_identity(otp_code=args.otp_code)
    if args.format == "json":
        _print_json(identity.to_dict())
    else:
        labels = [
            ("姓名", identity.name),
            ("学号", identity.student_id),
            ("性别", identity.sex),
            ("身份", identity.user_identity),
            ("单位", identity.department),
            ("学生类别", identity.student_type),
            ("专业", identity.speciality),
            ("研究方向", identity.direction),
            ("政治面貌", identity.politics),
            ("民族", identity.ethnic),
            ("籍贯", identity.native_place),
        ]
        out = ["> 个人身份信息 <", ""]
        out.extend(f"{label}: {value}" for label, value in labels if value)
        sys.stdout.write("\n".join(out) + "\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pypku3b", description="PKU 教学网/门户 client")
    parser.add_argument("--secrets-dir", default=None, help="dir with id/password files")
    parser.add_argument("--cookie-path", default=None, help="session cookie jar path")
    parser.add_argument("--seed-cookies", default=None, help="pku3b ua.json to warm-start from")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("assignment", aliases=["a"], help="course assignments")
    a_sub = a.add_subparsers(dest="sub", required=True)
    a_ls = a_sub.add_parser("list", aliases=["ls"])
    a_ls.add_argument("-a", "--all", action="store_true")
    a_ls.add_argument("--all-term", action="store_true")
    a_ls.add_argument("--format", choices=["text", "json"], default="text")
    a_ls.add_argument("-f", "--force", action="store_true")
    a_ls.add_argument("--otp-code", default="")
    a_ls.set_defaults(func=_cmd_assignment_list)

    ann = sub.add_parser("announcement", aliases=["ann"], help="course announcements")
    ann_sub = ann.add_subparsers(dest="sub", required=True)
    ann_ls = ann_sub.add_parser("list", aliases=["ls"])
    ann_ls.add_argument("--all-term", action="store_true")
    ann_ls.add_argument("-f", "--force", action="store_true")
    ann_ls.add_argument("--otp-code", default="")
    ann_ls.set_defaults(func=_cmd_announcement_list)
    ann_show = ann_sub.add_parser("show")
    ann_show.add_argument("id")
    ann_show.add_argument("--all-term", action="store_true")
    ann_show.add_argument("-f", "--force", action="store_true")
    ann_show.set_defaults(func=_cmd_announcement_show)

    ct = sub.add_parser("coursetable", aliases=["ct"], help="personal course table")
    ct.add_argument("-r", "--raw", action="store_true")
    ct.add_argument("-f", "--force", action="store_true")
    ct.add_argument("--otp-code", default="")
    ct.set_defaults(func=_cmd_coursetable)

    ident = sub.add_parser("identity", aliases=["id"], help="personal identity")
    ident.add_argument("--format", choices=["text", "json"], default="text")
    ident.add_argument("--otp-code", default="")
    ident.set_defaults(func=_cmd_identity)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Pku3bError as exc:
        sys.stderr.write(f"pypku3b: [{exc.code}] {exc.message}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
