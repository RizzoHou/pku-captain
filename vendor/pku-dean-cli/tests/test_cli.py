from __future__ import annotations

import json

import pytest

from dean import cli
from dean.client import DeanClient

# Map a URL substring to a fixture file.
_ROUTES = {
    "index.php": "index.html",
    "rules_school.php": "rules_school.html",
    "rules.php": "rules_national.html",
    "rules_info.php?id=20": "rule_valid.html",
    "rules_info.php?id=99999999": "rule_missing.html",
    "student_info.php?id=15": "guide_valid.html",
    "student_info.php?id=99999": "guide_missing.html",
    "notice_details.php?id=743": "notice_valid.html",
    "notice_details.php?id=99999999": "notice_missing.html",
    "notice.php": "notice_list.html",
    "download.php": "download.html",
    "openinfo.php": "openinfo.html",
}


@pytest.fixture(autouse=True)
def offline(monkeypatch, fixture):
    """Serve fixtures instead of hitting the network."""

    def fake_get_html(self, url, *, params=None):
        target = url
        if params and "id" in params:
            target = f"{url}?id={params['id']}"
        for needle, name in _ROUTES.items():
            if needle in target:
                return fixture(name)
        raise AssertionError(f"no fixture for {target}")

    monkeypatch.setattr(DeanClient, "get_html", fake_get_html)


def _run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out


def test_sidebar_json_envelope(capsys):
    code, out = _run(capsys, "--format", "json", "sidebar")
    assert code == 0
    payload = json.loads(out.out)
    assert payload["ok"] is True
    assert isinstance(payload["data"], list)
    assert payload["data"][0]["category"]


def test_rules_list_json(capsys):
    code, out = _run(capsys, "--format", "json", "rules", "list", "--scope", "national")
    assert code == 0
    data = json.loads(out.out)["data"]
    assert data["last_page"] == 1
    assert data["count"] == len(data["items"])


def test_rules_show_json(capsys):
    code, out = _run(capsys, "--format", "json", "rules", "show", "20")
    assert code == 0
    doc = json.loads(out.out)["data"]
    assert "学籍管理办法" in doc["title"]


def test_rules_show_missing_error_envelope(capsys):
    code, out = _run(capsys, "--format", "json", "rules", "show", "99999999")
    assert code == 1
    payload = json.loads(out.out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_guide_json(capsys):
    code, out = _run(capsys, "--format", "json", "guide", "15")
    assert code == 0
    doc = json.loads(out.out)["data"]
    assert doc["title"] == "选课"
    assert doc["sections"]


def test_guide_missing_error(capsys):
    code, out = _run(capsys, "--format", "json", "guide", "99999")
    assert code == 1
    assert json.loads(out.out)["error"]["code"] == "not_found"


def test_notice_list_json(capsys):
    code, out = _run(capsys, "--format", "json", "notice", "list")
    assert code == 0
    data = json.loads(out.out)["data"]
    assert data["last_page"] == 45
    assert data["count"] == len(data["items"])
    assert data["items"][0]["date"]


def test_notice_show_json(capsys):
    code, out = _run(capsys, "--format", "json", "notice", "show", "743")
    assert code == 0
    doc = json.loads(out.out)["data"]
    assert "期末考试" in doc["title"]
    assert doc["date"] == "2026-05-20"


def test_notice_show_missing_error(capsys):
    code, out = _run(capsys, "--format", "json", "notice", "show", "99999999")
    assert code == 1
    assert json.loads(out.out)["error"]["code"] == "not_found"


def test_human_format_default(capsys):
    code, out = _run(capsys, "download", "list")
    assert code == 0
    assert "files — page" in out.out


def test_download_list_json_shape(capsys):
    code, out = _run(capsys, "--format", "json", "download", "list")
    assert code == 0
    data = json.loads(out.out)["data"]
    assert {"page", "last_page", "count", "items"} <= data.keys()
