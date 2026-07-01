from __future__ import annotations

from dean.errors import DeanError

from src.tools import dean_resources
from src.tools.dean_resources import DeanResourcesTool

# The tool now calls the vendored ``dean`` library in-process (no subprocess),
# so tests fake ``dean.resources.*`` and assert on the resulting ToolResult and
# the arguments the wrapper forwarded — not on a subprocess argv.


def _dummy_factory(_timeout):
    # Resources are faked below, so the client is never used for HTTP.
    return None


def _patch_resource(monkeypatch, name, *, ret=None, exc=None):
    calls = []

    def fake(client, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append({"args": args, "kwargs": kwargs})
        if exc is not None:
            raise exc
        return ret

    monkeypatch.setattr(dean_resources.resources, name, fake)
    return calls


def _tool(client_factory=_dummy_factory) -> DeanResourcesTool:
    return DeanResourcesTool(client_factory=client_factory)


def test_sidebar_passes_through_list_data(monkeypatch) -> None:
    calls = _patch_resource(
        monkeypatch,
        "get_sidebar",
        ret=[{"category": "课程和培养", "title": "选课", "url": "https://x/15"}],
    )

    result = _tool().invoke({"action": "sidebar"})

    assert result.success is True
    assert result.data[0]["title"] == "选课"
    assert len(calls) == 1


def test_rules_list_scope_and_paging(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "list_rules", ret={"page": 2, "items": []})

    result = _tool().invoke({"action": "rules_list", "scope": "national", "page": 2})

    assert result.success is True
    assert calls[0]["args"] == ("national",)
    assert calls[0]["kwargs"] == {"page": 2}


def test_rules_list_default_scope_and_page(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "list_rules", ret={"page": 1, "items": []})

    _tool().invoke({"action": "rules_list"})

    # scope defaults to school; page defaults to 1.
    assert calls[0]["args"] == ("school",)
    assert calls[0]["kwargs"] == {"page": 1}


def test_guide_requires_int_id() -> None:
    result = _tool().invoke({"action": "guide"})

    assert result.success is False
    assert result.error == "`guide` requires integer `id`"


def test_rules_show_forwards_id(monkeypatch) -> None:
    calls = _patch_resource(
        monkeypatch, "show_rule", ret={"id": 20, "title": "学籍管理办法"}
    )

    result = _tool().invoke({"action": "rules_show", "id": 20})

    assert result.success is True
    assert result.data["id"] == 20
    assert calls[0]["args"] == (20,)


def test_notice_list_default_and_paging(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "list_notices", ret={"page": 3, "items": []})

    _tool().invoke({"action": "notice_list"})
    _tool().invoke({"action": "notice_list", "page": 3})

    assert calls[0]["kwargs"] == {"page": 1}
    assert calls[1]["kwargs"] == {"page": 3}


def test_notice_show_forwards_id(monkeypatch) -> None:
    calls = _patch_resource(
        monkeypatch, "show_notice", ret={"id": 743, "title": "期末考试安排通知"}
    )

    result = _tool().invoke({"action": "notice_show", "id": 743})

    assert result.success is True
    assert result.data["id"] == 743
    assert calls[0]["args"] == (743,)


def test_notice_show_requires_int_id() -> None:
    result = _tool().invoke({"action": "notice_show"})

    assert result.success is False
    assert result.error == "`notice show` requires integer `id`"


def test_error_surfaces_message(monkeypatch) -> None:
    _patch_resource(
        monkeypatch, "show_rule", exc=DeanError("no rule found", code="not_found")
    )

    result = _tool().invoke({"action": "rules_show", "id": 99999999})

    assert result.success is False
    assert result.error == "no rule found"


def test_download_get_single_id_uses_download_timeout(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "download_file", ret="/tmp/out/手册.pdf")
    timeouts: list[float] = []

    def factory(timeout):
        timeouts.append(timeout)
        return None

    result = _tool(factory).invoke(
        {"action": "download_get", "id": 224, "output_dir": "/tmp/dl"}
    )

    assert result.success is True
    assert result.data == {"saved": ["/tmp/out/手册.pdf"], "count": 1}
    # resources.download_file(client, kind, fid, output_dir)
    assert calls[0]["args"] == ("download", 224, "/tmp/dl")
    # downloads stream a binary → the longer ceiling is used, not the read timeout.
    assert timeouts == [dean_resources.DOWNLOAD_TIMEOUT]


def test_download_get_multi_id_order(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "download_file", ret="/tmp/x")

    # `id` is prepended to `ids`, preserving the explicit-then-list order.
    _tool().invoke(
        {"action": "download_get", "id": 224, "ids": [225], "output_dir": "/tmp/dl"}
    )

    fids = [c["args"][1] for c in calls]
    assert fids == [224, 225]


def test_openinfo_get_default_output_dir(monkeypatch) -> None:
    calls = _patch_resource(monkeypatch, "download_file", ret="/tmp/x")

    _tool().invoke({"action": "openinfo_get", "ids": [17]})

    kind, fid, out_dir = calls[0]["args"]
    assert (kind, fid) == ("openinfo", 17)
    # falls back to the gitignored downloads/dean/<kind> directory.
    assert out_dir.endswith("/downloads/dean/openinfo")


def test_download_get_requires_id() -> None:
    result = _tool().invoke({"action": "download_get"})

    assert result.success is False
    assert result.error == "`download_get` requires `id` or `ids`"


def test_unknown_action() -> None:
    result = _tool().invoke({"action": "nope"})

    assert result.success is False
    assert "unknown action" in str(result.error)


def test_fetch_dean_surfaces_error() -> None:
    def boom(_client):
        raise DeanError("boom", code="network_error")

    result = dean_resources.fetch_dean(boom, client_factory=_dummy_factory)

    assert result["ok"] is False
    assert result["error"] == "boom"
