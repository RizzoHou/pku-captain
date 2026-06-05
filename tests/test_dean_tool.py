from __future__ import annotations

import json
import subprocess

from src.tools.dean_resources import DeanResourcesTool, run_dean


def _fake_envelope(stdout: str, returncode: int = 0):
    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        fake_run.calls.append(argv)
        fake_run.kwargs.append(kwargs)
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    fake_run.calls = []
    fake_run.kwargs = []
    return fake_run


def _patch(monkeypatch, fake_run) -> None:
    monkeypatch.setattr("src.tools.dean_resources.resolve_executable", lambda _exe: "/bin/dean")
    monkeypatch.setattr("src.tools.dean_resources.subprocess.run", fake_run)


def test_sidebar_passes_through_list_data(monkeypatch) -> None:
    fake_run = _fake_envelope(
        json.dumps(
            {
                "ok": True,
                "data": [{"category": "课程和培养", "title": "选课", "url": "https://x/15"}],
            }
        )
    )
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke({"action": "sidebar"})

    assert result.success is True
    assert result.data[0]["title"] == "选课"
    assert fake_run.calls == [["/bin/dean", "--format", "json", "sidebar"]]


def test_rules_list_scope_and_paging_argv(monkeypatch) -> None:
    fake_run = _fake_envelope(json.dumps({"ok": True, "data": {"page": 2, "items": []}}))
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke(
        {"action": "rules_list", "scope": "national", "page": 2}
    )

    assert result.success is True
    assert fake_run.calls == [
        ["/bin/dean", "--format", "json", "rules", "list", "--scope", "national", "--page", "2"]
    ]


def test_rules_list_default_scope_no_page_flag(monkeypatch) -> None:
    fake_run = _fake_envelope(json.dumps({"ok": True, "data": {"page": 1, "items": []}}))
    _patch(monkeypatch, fake_run)

    DeanResourcesTool().invoke({"action": "rules_list"})

    # page 1 is the CLI default → no --page flag; scope defaults to school.
    assert fake_run.calls == [
        ["/bin/dean", "--format", "json", "rules", "list", "--scope", "school"]
    ]


def test_guide_requires_int_id() -> None:
    result = DeanResourcesTool().invoke({"action": "guide"})

    assert result.success is False
    assert result.error == "`guide` requires integer `id`"


def test_rules_show_builds_subcommand_argv(monkeypatch) -> None:
    fake_run = _fake_envelope(json.dumps({"ok": True, "data": {"id": 20, "title": "学籍管理办法"}}))
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke({"action": "rules_show", "id": 20})

    assert result.success is True
    assert result.data["id"] == 20
    assert fake_run.calls == [["/bin/dean", "--format", "json", "rules", "show", "20"]]


def test_notice_list_default_no_page_flag(monkeypatch) -> None:
    fake_run = _fake_envelope(json.dumps({"ok": True, "data": {"page": 1, "items": []}}))
    _patch(monkeypatch, fake_run)

    DeanResourcesTool().invoke({"action": "notice_list"})

    assert fake_run.calls == [["/bin/dean", "--format", "json", "notice", "list"]]


def test_notice_list_paging_argv(monkeypatch) -> None:
    fake_run = _fake_envelope(json.dumps({"ok": True, "data": {"page": 3, "items": []}}))
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke({"action": "notice_list", "page": 3})

    assert result.success is True
    assert fake_run.calls == [
        ["/bin/dean", "--format", "json", "notice", "list", "--page", "3"]
    ]


def test_notice_show_builds_subcommand_argv(monkeypatch) -> None:
    fake_run = _fake_envelope(
        json.dumps({"ok": True, "data": {"id": 743, "title": "期末考试安排通知"}})
    )
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke({"action": "notice_show", "id": 743})

    assert result.success is True
    assert result.data["id"] == 743
    assert fake_run.calls == [["/bin/dean", "--format", "json", "notice", "show", "743"]]


def test_notice_show_requires_int_id() -> None:
    result = DeanResourcesTool().invoke({"action": "notice_show"})

    assert result.success is False
    assert result.error == "`notice show` requires integer `id`"


def test_error_envelope_surfaces_message(monkeypatch) -> None:
    fake_run = _fake_envelope(
        json.dumps({"ok": False, "error": {"code": "not_found", "message": "no rule found"}}),
        returncode=1,
    )
    _patch(monkeypatch, fake_run)

    result = DeanResourcesTool().invoke({"action": "rules_show", "id": 99999999})

    assert result.success is False
    assert result.error == "no rule found"


def test_unknown_action() -> None:
    result = DeanResourcesTool().invoke({"action": "nope"})

    assert result.success is False
    assert "unknown action" in str(result.error)


def test_run_dean_invalid_json(monkeypatch) -> None:
    def fake_run2(argv, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(argv, 1, stdout="not json", stderr="boom")

    monkeypatch.setattr("src.tools.dean_resources.resolve_executable", lambda _exe: "/bin/dean")
    monkeypatch.setattr("src.tools.dean_resources.subprocess.run", fake_run2)

    result = run_dean(["sidebar"])

    assert result["ok"] is False
    assert "boom" in result["error"]
