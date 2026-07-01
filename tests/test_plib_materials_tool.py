from __future__ import annotations

from plib_cli.config import Credentials
from plib_cli.errors import AuthError

from src.tools.plib_materials import DOWNLOAD_TIMEOUT, PLibMaterialsTool

# The tool now drives the vendored ``plib_cli`` library in-process (no
# subprocess). Tests inject a fake PlibClient via ``client_factory`` and a
# nonexistent ``secrets_dir`` so no real repo credentials are read.

_NO_SECRETS = "/nonexistent/plib"


class _Obj:
    def __init__(self, data) -> None:  # noqa: ANN001
        self._data = data

    def to_dict(self):
        return self._data


class _FakeClient:
    def __init__(self, *, profile_error: Exception | None = None) -> None:
        self.calls: dict = {}
        self._profile_error = profile_error

    def search_all(self, query, *, type=None, time=None, sort="relevance", limit=None):  # noqa: A002, ANN001
        self.calls["search_all"] = {
            "query": query,
            "type": type,
            "time": time,
            "sort": sort,
            "limit": limit,
        }
        return _Obj({"results": [{"id": 727, "title": "高等数学试卷", "course": "高等数学"}]})

    def login(self) -> None:
        self.calls["login"] = True

    def quota_remaining(self, *, refresh: bool = False):
        return 9

    def profile(self):
        if self._profile_error is not None:
            raise self._profile_error
        return _Obj({"download_remaining": 9})

    def material(self, material_id):  # noqa: ANN001
        self.calls["material"] = material_id
        return _Obj({"id": material_id})

    def download(self, material_id, dest_dir=".", *, force=False):  # noqa: ANN001
        self.calls.setdefault("download", []).append((material_id, dest_dir))
        return _Obj({"id": material_id, "path": f"{dest_dir}/{material_id}.pdf"})


def _tool(client: _FakeClient, record: list | None = None) -> PLibMaterialsTool:
    def factory(timeout, credentials):  # noqa: ANN001
        if record is not None:
            record.append({"timeout": timeout, "credentials": credentials})
        return client

    return PLibMaterialsTool(client_factory=factory, secrets_dir=_NO_SECRETS)


def test_plib_search_forwards_filters(monkeypatch) -> None:
    client = _FakeClient()
    result = _tool(client).invoke(
        {
            "action": "search",
            "query": "高等数学",
            "type": "试卷",
            "sort": "downloads",
            "time": "month",
            "limit": 5,
        }
    )

    assert result.success is True
    assert result.data["results"][0]["id"] == 727
    assert client.calls["search_all"] == {
        "query": "高等数学",
        "type": "试卷",
        "time": "month",
        "sort": "downloads",
        "limit": 5,
    }


def test_plib_search_defaults_and_time_all_maps_to_empty() -> None:
    client = _FakeClient()
    _tool(client).invoke({"action": "search", "query": "x", "time": "all"})

    call = client.calls["search_all"]
    assert call["time"] == ""  # "all" → "" (site's <select> value)
    assert call["sort"] == "relevance"  # default
    assert call["type"] is None  # default
    assert call["limit"] == 10  # default


def test_plib_login_passes_credentials_to_client() -> None:
    client = _FakeClient()
    record: list = []
    result = _tool(client, record).invoke(
        {"action": "login", "email": "user@example.com", "password": "secret"}
    )

    assert result.success is True
    assert result.data == {"status": "logged_in", "quota_remaining": 9}
    assert client.calls["login"] is True
    assert record[0]["credentials"] == Credentials("user@example.com", "secret")


def test_plib_error_surfaces_message() -> None:
    client = _FakeClient(profile_error=AuthError("not logged in"))
    result = _tool(client).invoke({"action": "quota"})

    assert result.success is False
    assert result.error == "not logged in"


def test_plib_download_uses_download_timeout_and_id_order() -> None:
    client = _FakeClient()
    record: list = []
    result = _tool(client, record).invoke(
        {"action": "download", "id": 224, "ids": [225], "output_dir": "/tmp/dl"}
    )

    assert result.success is True
    # `id` is prepended to `ids`, preserving explicit-then-list order.
    assert [mid for mid, _dir in client.calls["download"]] == [224, 225]
    assert result.data["quota_remaining"] == 9
    # downloads stream a file → the longer ceiling is used, not the read timeout.
    assert record[0]["timeout"] == DOWNLOAD_TIMEOUT


def test_plib_download_requires_id() -> None:
    result = PLibMaterialsTool(secrets_dir=_NO_SECRETS).invoke({"action": "download"})

    assert result.success is False
    assert "`download` requires" in str(result.error)
