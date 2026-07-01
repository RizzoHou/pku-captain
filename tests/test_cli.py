"""CLI pure helpers (no network)."""

from treehole.cli import _fmt_time


def test_fmt_time_renders_beijing_regardless_of_host_tz():
    # 1780586987 == 2026-06-04 15:29:47 UTC == 23:29:47 Beijing (UTC+8).
    assert _fmt_time(1780586987) == "2026-06-04 23:29:47"
    assert _fmt_time("1780586987") == "2026-06-04 23:29:47"  # API may hand back a string


def test_fmt_time_missing_or_bad_input():
    assert _fmt_time(None) == "?"
    assert _fmt_time(0) == "?"
    assert _fmt_time("") == "?"
    assert _fmt_time("notanumber") == "?"
