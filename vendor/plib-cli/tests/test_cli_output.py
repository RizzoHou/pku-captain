"""CLI output-layer formatting (no network).

Guards the `_emit` dispatch: in table/interactive mode every subcommand must
render a human-readable form (not a JSON dump), while JSON mode stays the stable
pku-captain envelope. This is the layer that previously had no test, which is
how `quota`/`login`/`download` came to print JSON even when interactive.
"""

from __future__ import annotations

import argparse
import json

from plib_cli.cli import _emit
from plib_cli.models import DownloadResult, Profile


def _args(command: str, **extra) -> argparse.Namespace:
    return argparse.Namespace(command=command, **extra)


def _emit_table(data, command: str, **extra) -> str:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit(data, as_json=False, args=_args(command, **extra))
    return buf.getvalue()


def _emit_json(data, command: str, **extra) -> dict:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit(data, as_json=True, args=_args(command, **extra))
    return json.loads(buf.getvalue())


# -- table mode is human-readable for every subcommand -------------------


def test_quota_table_is_human_readable() -> None:
    out = _emit_table({"download_remaining": 7}, "quota")
    assert "downloads remaining today: 7" in out
    assert "{" not in out  # not a JSON dump


def test_quota_table_unknown() -> None:
    out = _emit_table({"download_remaining": None}, "quota")
    assert "downloads remaining today: unknown" in out


def test_login_table_is_human_readable() -> None:
    out = _emit_table({"status": "logged_in", "quota_remaining": 9}, "login")
    assert "logged in" in out
    assert "9 downloads remaining today" in out
    assert "{" not in out


def test_download_table_is_human_readable() -> None:
    data = {
        "downloads": [
            DownloadResult(42, "/tmp/x.zip", "x.zip", 2048, 4).to_dict(),
        ],
        "quota_remaining": 4,
    }
    out = _emit_table(data, "download")
    assert "[42] x.zip" in out
    assert "/tmp/x.zip" in out
    assert "2.0 KB" in out
    assert "4 downloads remaining today" in out
    assert "{" not in out


# -- JSON mode stays the stable envelope (pku-captain contract) ----------


def test_quota_json_envelope_unchanged() -> None:
    assert _emit_json(Profile(download_remaining=7).to_dict(), "quota") == {
        "ok": True,
        "data": {"download_remaining": 7},
    }


def test_login_json_envelope_unchanged() -> None:
    payload = {"status": "logged_in", "quota_remaining": 9}
    assert _emit_json(payload, "login") == {"ok": True, "data": payload}


def test_download_json_envelope_unchanged() -> None:
    payload = {
        "downloads": [DownloadResult(42, "/tmp/x.zip", "x.zip", 2048, 4).to_dict()],
        "quota_remaining": 4,
    }
    assert _emit_json(payload, "download") == {"ok": True, "data": payload}
