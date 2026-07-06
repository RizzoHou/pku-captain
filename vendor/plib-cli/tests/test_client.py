"""Download-path and server-quota behaviour (no network).

``PlibClient`` is built via ``__new__`` so ``__init__`` (which opens a session
and loads the cookie jar) is skipped; ``profile``/``_request`` are stubbed to
drive the quota logic without touching pkuhub.cn.
"""

from __future__ import annotations

import pytest

from plib_cli.client import PlibClient
from plib_cli.errors import NetworkError, ParseError, QuotaError
from plib_cli.models import Profile


def _client(remaining: int | None) -> PlibClient:
    c = PlibClient.__new__(PlibClient)
    c._download_remaining = None
    c.profile = lambda: Profile(download_remaining=remaining)  # type: ignore[method-assign]
    # download() harvests a CSRF token from the material page before POSTing;
    # stub that fetch so the no-network tests never touch _request for it.
    c._get_html = lambda path: '<meta name="csrf-token" content="tok">'  # type: ignore[method-assign]
    return c


class _FakeResp:
    def __init__(self, content: bytes, name: str) -> None:
        self.status_code = 200
        self.content = content
        self.url = "https://pkuhub.cn/download/42"
        self.headers = {
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{name}"',
        }


def test_download_decrements_server_quota(tmp_path) -> None:
    c = _client(6)
    c._request = lambda *a, **k: _FakeResp(b"PK\x03\x04data", "x.zip")  # type: ignore[method-assign]

    first = c.download(42, tmp_path)
    assert first.quota_remaining == 5  # 6 (server) - 1 (this download)
    assert first.bytes == len(b"PK\x03\x04data")
    assert (tmp_path / "x.zip").read_bytes() == b"PK\x03\x04data"

    second = c.download(42, tmp_path)
    assert second.quota_remaining == 4  # cached, decremented again — no refetch
    assert c.quota_remaining() == 4


def test_download_posts_with_csrf_header(tmp_path) -> None:
    """pkuhub moved /download/<id> to a CSRF-guarded POST — a GET now 405s."""
    c = _client(6)
    calls: dict[str, object] = {}

    def fake_request(method, path, **kwargs):  # noqa: ANN001, ANN202
        calls["method"] = method
        calls["path"] = path
        calls["headers"] = kwargs.get("headers")
        calls["retry"] = kwargs.get("retry")
        return _FakeResp(b"PK\x03\x04data", "x.zip")

    c._request = fake_request  # type: ignore[method-assign]
    c.download(42, tmp_path)

    assert calls["method"] == "POST"
    assert calls["path"] == "/download/42"
    assert calls["headers"] == {"X-CSRFToken": "tok"}
    assert calls["retry"] is False


def test_download_blocked_when_no_quota_left(tmp_path) -> None:
    c = _client(0)
    with pytest.raises(QuotaError):
        c.download(42, tmp_path)


def test_force_bypasses_guard_even_at_zero(tmp_path) -> None:
    c = _client(0)
    c._request = lambda *a, **k: _FakeResp(b"data", "y.zip")  # type: ignore[method-assign]
    # --force skips the read entirely, so quota stays unknown (None) for the result.
    result = c.download(42, tmp_path, force=True)
    assert result.quota_remaining is None


@pytest.mark.parametrize("exc", [NetworkError("timeout"), ParseError("markup drift")])
def test_quota_remaining_fails_open(exc: Exception) -> None:
    c = PlibClient.__new__(PlibClient)
    c._download_remaining = None

    def boom() -> Profile:
        raise exc

    c.profile = boom  # type: ignore[method-assign]
    assert c.quota_remaining() is None  # transient failure → unknown, not raised
