"""Date resolution + on-disk cache for ``PKU3bAnnouncementsTool``.

``announcement list`` carries no dates, so ``resolve_dates`` fetches each
announcement's detail to attach a ``posted_date`` and caches the result (a
definitive "no date" included) so refreshes only fetch new ids.
"""

from __future__ import annotations

from typing import Any

import src.tools.pku3b_announcements as ann
from src.tools.pku3b import Pku3bRun, Pku3bTimeoutError
from src.tools.pku3b_announcements import (
    AnnouncementDateCache,
    PKU3bAnnouncementsTool,
)

_LIST_STDOUT = (
    "> 课程公告 (3) <\n\n"
    "[ 1] 课程A > 标题一 aaaaaaaa\n"
    "[ 2] 课程B > 标题二 bbbbbbbb\n"
    "[ 3] 课程C > 标题三 cccccccc\n"
)


def _detail(posted_line: str) -> str:
    return (
        "> 公告详情 <\n\n"
        "课程A > 标题一\n"
        "ID: aaaaaaaa\n\n"
        f"{posted_line}"
        "正文内容\n"
    )


def _make_runner(
    details: dict[str, str], calls: list[list[str]], timeout_ids: set[str] | None = None
):
    """Fake ``run_pku3b`` dispatching on the cli args, recording every call."""
    timeout_ids = timeout_ids or set()

    def fake_run(args: Any, *, executable: str, timeout: float) -> Pku3bRun:
        cli = list(args)
        calls.append(cli)
        if "list" in cli:
            return Pku3bRun(returncode=0, stdout=_LIST_STDOUT, stderr="")
        if "show" in cli:
            ann_id = cli[cli.index("show") + 1]
            if ann_id in timeout_ids:
                raise Pku3bTimeoutError("boom")
            return Pku3bRun(returncode=0, stdout=details[ann_id], stderr="")
        raise AssertionError(f"unexpected pku3b call: {cli}")

    return fake_run


def test_resolve_dates_attaches_posted_date(monkeypatch, tmp_path) -> None:
    details = {
        "aaaaaaaa": _detail("发布时间: 2026年6月3日 星期三 下午04时04分00秒 CST\n"),
        "bbbbbbbb": _detail("发布时间: 2026年4月11日 星期六 上午09时00分00秒 CST\n"),
        # No 发布时间 line — pku3b reports none (~half of items).
        "cccccccc": _detail(""),
    }
    calls: list[list[str]] = []
    monkeypatch.setattr(ann, "run_pku3b", _make_runner(details, calls))

    cache = AnnouncementDateCache(tmp_path / "dates.json")
    tool = PKU3bAnnouncementsTool(date_cache=cache)
    result = tool.invoke({"resolve_dates": True})

    assert result.success
    by_id = {a["id"]: a for a in result.data["announcements"]}
    assert by_id["aaaaaaaa"]["posted_date"] == "2026-06-03"
    assert by_id["bbbbbbbb"]["posted_date"] == "2026-04-11"
    assert by_id["cccccccc"]["posted_date"] is None
    # 1 list + 3 detail fetches.
    assert sum(1 for c in calls if "show" in c) == 3


def test_resolved_dates_are_cached_no_refetch(monkeypatch, tmp_path) -> None:
    details = {
        "aaaaaaaa": _detail("发布时间: 2026年6月3日 星期三 下午04时04分00秒 CST\n"),
        "bbbbbbbb": _detail("发布时间: 2026年4月11日 星期六 上午09时00分00秒 CST\n"),
        "cccccccc": _detail(""),  # definitive no-date → cached as None
    }
    cache = AnnouncementDateCache(tmp_path / "dates.json")

    calls1: list[list[str]] = []
    monkeypatch.setattr(ann, "run_pku3b", _make_runner(details, calls1))
    PKU3bAnnouncementsTool(date_cache=cache).invoke({"resolve_dates": True})
    assert sum(1 for c in calls1 if "show" in c) == 3

    # Second invocation (fresh cache object, same file) refetches nothing —
    # the no-date item too, since None is cached as a definitive answer.
    calls2: list[list[str]] = []
    monkeypatch.setattr(ann, "run_pku3b", _make_runner(details, calls2))
    result = PKU3bAnnouncementsTool(
        date_cache=AnnouncementDateCache(tmp_path / "dates.json")
    ).invoke({"resolve_dates": True})
    assert sum(1 for c in calls2 if "show" in c) == 0
    by_id = {a["id"]: a for a in result.data["announcements"]}
    assert by_id["aaaaaaaa"]["posted_date"] == "2026-06-03"
    assert by_id["cccccccc"]["posted_date"] is None


def test_fetch_failure_is_not_cached(monkeypatch, tmp_path) -> None:
    details = {
        "aaaaaaaa": _detail("发布时间: 2026年6月3日 星期三 下午04时04分00秒 CST\n"),
        "bbbbbbbb": _detail("发布时间: 2026年6月1日 星期一 上午09时00分00秒 CST\n"),
        "cccccccc": _detail("发布时间: 2026年5月20日 星期二 上午09时00分00秒 CST\n"),
    }
    cache = AnnouncementDateCache(tmp_path / "dates.json")

    # First pass: 'bbbbbbbb' times out → uncached, posted_date None for now.
    calls1: list[list[str]] = []
    monkeypatch.setattr(
        ann, "run_pku3b", _make_runner(details, calls1, timeout_ids={"bbbbbbbb"})
    )
    r1 = PKU3bAnnouncementsTool(date_cache=cache).invoke({"resolve_dates": True})
    assert {a["id"]: a["posted_date"] for a in r1.data["announcements"]}[
        "bbbbbbbb"
    ] is None

    # Second pass without the timeout: only the failed id is refetched.
    calls2: list[list[str]] = []
    monkeypatch.setattr(ann, "run_pku3b", _make_runner(details, calls2))
    r2 = PKU3bAnnouncementsTool(
        date_cache=AnnouncementDateCache(tmp_path / "dates.json")
    ).invoke({"resolve_dates": True})
    shown = [c[c.index("show") + 1] for c in calls2 if "show" in c]
    assert shown == ["bbbbbbbb"]
    assert {a["id"]: a["posted_date"] for a in r2.data["announcements"]}[
        "bbbbbbbb"
    ] == "2026-06-01"


def test_resolve_dates_off_does_not_fetch(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(ann, "run_pku3b", _make_runner({}, calls))
    tool = PKU3bAnnouncementsTool(date_cache=AnnouncementDateCache(tmp_path / "d.json"))

    result = tool.invoke({})  # resolve_dates defaults False

    assert result.success
    assert all("posted_date" not in a for a in result.data["announcements"])
    assert all("show" not in c for c in calls)
