from __future__ import annotations

import json

from src.tools import dean_updates
from src.tools.dean_updates import DeanUpdatesTool

# DeanUpdatesTool now fetches each source in-process via ``dean.resources.*``
# (no subprocess). Tests fake those functions — keyed by source — and pass a
# dummy client factory so no real DeanClient / network is involved.


def _dummy_factory(_timeout):
    return None


def _patch_sources(monkeypatch, pages: dict[str, list[dict[str, object]]]) -> None:
    def list_rules(_client, scope, **_kw):  # noqa: ANN001
        return {"items": pages.get(f"rules_{scope}", [])}

    def list_notices(_client, **_kw):  # noqa: ANN001
        return {"items": pages.get("notice", [])}

    def list_files(_client, kind, **_kw):  # noqa: ANN001
        return {"items": pages.get(kind, [])}

    monkeypatch.setattr(dean_updates.resources, "list_rules", list_rules)
    monkeypatch.setattr(dean_updates.resources, "list_notices", list_notices)
    monkeypatch.setattr(dean_updates.resources, "list_files", list_files)


def _tool(tmp_path) -> DeanUpdatesTool:
    return DeanUpdatesTool(
        state_path=tmp_path / "dean.json", client_factory=_dummy_factory
    )


def test_first_dean_update_check_establishes_baseline(tmp_path, monkeypatch) -> None:
    _patch_sources(
        monkeypatch,
        {
            "rules_school": [{"id": 1, "title": "学籍管理办法"}],
            "openinfo": [{"id": 9, "title": "信息公开"}],
        },
    )
    tool = _tool(tmp_path)

    result = tool.invoke({})

    assert result.success is True
    assert result.data["baseline_only"] is True
    assert result.data["updates"] == []
    state = json.loads((tmp_path / "dean.json").read_text(encoding="utf-8"))
    assert "rules_school:1" in state["seen"]
    assert "openinfo:9" in state["seen"]


def test_dean_update_check_surfaces_only_new_items(tmp_path, monkeypatch) -> None:
    _patch_sources(monkeypatch, {"rules_school": [{"id": 1, "title": "旧办法"}]})
    tool = _tool(tmp_path)
    tool.invoke({})

    _patch_sources(
        monkeypatch,
        {
            "rules_school": [
                {"id": 1, "title": "旧办法"},
                {"id": 2, "title": "新办法", "date": "2026-06-05"},
            ]
        },
    )

    result = tool.invoke({"limit": 5})

    assert result.success is True
    assert result.data["baseline_only"] is False
    assert result.data["new_count"] == 1
    assert result.data["updates"][0]["key"] == "rules_school:2"
    assert result.data["updates"][0]["source_label"] == "校级规章"


def test_dean_update_includes_notices_and_full_snapshot(tmp_path, monkeypatch) -> None:
    _patch_sources(
        monkeypatch,
        {
            "notice": [{"id": 746, "title": "四六级考前通知", "date": "2026-06-03"}],
            "rules_school": [{"id": 1, "title": "学籍管理办法"}],
        },
    )
    tool = _tool(tmp_path)

    result = tool.invoke({})

    assert result.success is True
    # Notices are a polled source, keyed `notice:<id>`.
    keys = {item["key"] for item in result.data["items"]}
    assert "notice:746" in keys
    assert "rules_school:1" in keys
    # The full snapshot feeds the GUI accumulator; carries id + date for windowing.
    notice = next(i for i in result.data["items"] if i["key"] == "notice:746")
    assert notice["item_id"] == "746"
    assert notice["date"] == "2026-06-03"
    assert notice["source_label"] == "通知公告"


def test_dean_update_check_errors_when_all_sources_fail(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        dean_updates,
        "fetch_dean",
        lambda _call, **_kwargs: {"ok": False, "error": "offline"},
    )
    tool = _tool(tmp_path)

    result = tool.invoke({})

    assert result.success is False
    assert "offline" in str(result.error)
