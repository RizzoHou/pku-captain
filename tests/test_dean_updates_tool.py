from __future__ import annotations

import json

from src.tools.dean_updates import DeanUpdatesTool


def _patch_dean(monkeypatch, pages: dict[str, list[dict[str, object]]]) -> None:
    def fake_run(args, **_kwargs):  # noqa: ANN001
        key = " ".join(args)
        return {"ok": True, "data": {"items": pages.get(key, [])}}

    monkeypatch.setattr("src.tools.dean_updates.run_dean", fake_run)


def test_first_dean_update_check_establishes_baseline(tmp_path, monkeypatch) -> None:
    _patch_dean(
        monkeypatch,
        {
            "rules list --scope school": [{"id": 1, "title": "学籍管理办法"}],
            "openinfo list": [{"id": 9, "title": "信息公开"}],
        },
    )
    tool = DeanUpdatesTool(state_path=tmp_path / "dean.json")

    result = tool.invoke({})

    assert result.success is True
    assert result.data["baseline_only"] is True
    assert result.data["updates"] == []
    state = json.loads((tmp_path / "dean.json").read_text(encoding="utf-8"))
    assert "rules_school:1" in state["seen"]
    assert "openinfo:9" in state["seen"]


def test_dean_update_check_surfaces_only_new_items(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "dean.json"
    _patch_dean(
        monkeypatch,
        {"rules list --scope school": [{"id": 1, "title": "旧办法"}]},
    )
    tool = DeanUpdatesTool(state_path=state_path)
    tool.invoke({})

    _patch_dean(
        monkeypatch,
        {
            "rules list --scope school": [
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
    _patch_dean(
        monkeypatch,
        {
            "notice list": [
                {"id": 746, "title": "四六级考前通知", "date": "2026-06-03"}
            ],
            "rules list --scope school": [{"id": 1, "title": "学籍管理办法"}],
        },
    )
    tool = DeanUpdatesTool(state_path=tmp_path / "dean.json")

    result = tool.invoke({})

    assert result.success is True
    # Notices are now a polled source, keyed `notice:<id>`.
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
        "src.tools.dean_updates.run_dean",
        lambda _args, **_kwargs: {"ok": False, "error": "offline"},
    )
    tool = DeanUpdatesTool(state_path=tmp_path / "dean.json")

    result = tool.invoke({})

    assert result.success is False
    assert "offline" in str(result.error)
