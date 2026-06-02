from __future__ import annotations

import json
import subprocess

from src.tools.plib_materials import PLibMaterialsTool, run_plib


def test_plib_search_success(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "data": {
                        "results": [
                            {
                                "id": 727,
                                "title": "高等数学试卷",
                                "course": "高等数学",
                            }
                        ]
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("src.tools.plib_materials.resolve_executable", lambda _exe: "/bin/plib")
    monkeypatch.setattr("src.tools.plib_materials.subprocess.run", fake_run)

    result = PLibMaterialsTool().invoke(
        {
            "action": "search",
            "query": "高等数学",
            "type": "试卷",
            "sort": "downloads",
            "limit": 5,
        }
    )

    assert result.success is True
    assert result.data["results"][0]["id"] == 727
    assert calls == [
        [
            "/bin/plib",
            "--format",
            "json",
            "search",
            "高等数学",
            "--limit",
            "5",
            "--type",
            "试卷",
            "--sort",
            "downloads",
        ]
    ]


def test_plib_login_passes_credentials_via_env(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        seen["argv"] = argv
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "data": {"status": "logged_in", "quota_remaining": 9},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("src.tools.plib_materials.resolve_executable", lambda _exe: "/bin/plib")
    monkeypatch.setattr("src.tools.plib_materials.subprocess.run", fake_run)

    result = PLibMaterialsTool().invoke(
        {"action": "login", "email": "user@example.com", "password": "secret"}
    )

    assert result.success is True
    assert result.data["quota_remaining"] == 9
    assert seen["argv"] == ["/bin/plib", "--format", "json", "login"]
    assert seen["env"]["PLIB_EMAIL"] == "user@example.com"
    assert seen["env"]["PLIB_PASSWORD"] == "secret"


def test_plib_error_envelope(monkeypatch) -> None:
    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=json.dumps({"ok": False, "error": {"message": "not logged in"}}),
            stderr="",
        )

    monkeypatch.setattr("src.tools.plib_materials.resolve_executable", lambda _exe: "/bin/plib")
    monkeypatch.setattr("src.tools.plib_materials.subprocess.run", fake_run)

    result = PLibMaterialsTool().invoke({"action": "quota"})

    assert result.success is False
    assert result.error == "not logged in"


def test_run_plib_invalid_json(monkeypatch) -> None:
    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(argv, 1, stdout="not json", stderr="boom")

    monkeypatch.setattr("src.tools.plib_materials.resolve_executable", lambda _exe: "/bin/plib")
    monkeypatch.setattr("src.tools.plib_materials.subprocess.run", fake_run)

    result = run_plib(["quota"])

    assert result["ok"] is False
    assert "boom" in result["error"]


def test_plib_download_requires_id() -> None:
    result = PLibMaterialsTool().invoke({"action": "download"})

    assert result.success is False
    assert "`download` requires" in str(result.error)
