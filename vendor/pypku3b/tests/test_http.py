import json

from pypku3b.http import HttpClient, default_ca_bundle


def test_cookie_roundtrip(tmp_path):
    path = tmp_path / "cookies.json"
    client = HttpClient(cookie_path=path)
    client.session.cookies.set("s_session_id", "ABC", domain="course.pku.edu.cn")
    client.save_cookies()
    assert path.exists()

    reloaded = HttpClient(cookie_path=path)
    assert reloaded.session.cookies.get("s_session_id") == "ABC"


def test_pku3b_ua_json_warm_start(tmp_path):
    seed = tmp_path / "ua.json"
    seed.write_text(
        json.dumps(
            [
                {
                    "raw_cookie": "s_session_id=8F63; HttpOnly; Secure; Path=/",
                    "path": ["/", True],
                    "domain": {"HostOnly": "course.pku.edu.cn"},
                    "expires": "SessionEnd",
                }
            ]
        ),
        encoding="utf-8",
    )
    # No own cookie file -> seed is imported.
    client = HttpClient(cookie_path=tmp_path / "mine.json", seed_cookie_path=seed)
    assert client.session.cookies.get("s_session_id") == "8F63"


def test_default_ca_bundle_returns_path_or_true():
    verify = default_ca_bundle()
    assert verify is True or isinstance(verify, str)
