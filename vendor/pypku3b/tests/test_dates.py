from pypku3b.dates import parse_deadline_iso, parse_posted_date


def test_deadline_pm_adds_12h():
    assert (
        parse_deadline_iso("2026年4月4日 星期五 下午11:59")
        == "2026-04-04T23:59:00+08:00"
    )


def test_deadline_am_kept():
    assert (
        parse_deadline_iso("2025年9月24日 星期三 上午9:05")
        == "2025-09-24T09:05:00+08:00"
    )


def test_deadline_noon_pm_not_double_shifted():
    # 下午12:00 -> hour already >= 12, must not add another 12.
    assert (
        parse_deadline_iso("2026年1月1日 星期四 下午12:00")
        == "2026-01-01T12:00:00+08:00"
    )


def test_deadline_embedded_in_prose():
    raw = "截止日期： 2026年4月4日 星期五 下午11:59 (剩余 3 天)"
    assert parse_deadline_iso(raw) == "2026-04-04T23:59:00+08:00"


def test_deadline_none_and_unmatched():
    assert parse_deadline_iso(None) is None
    assert parse_deadline_iso("") is None
    assert parse_deadline_iso("no date here") is None


def test_posted_date():
    assert (
        parse_posted_date("发布时间: 2026年4月11日 星期六 下午04时04分00秒 CST")
        == "2026-04-11"
    )
    assert parse_posted_date("发帖者: 老师") is None
    assert parse_posted_date(None) is None
