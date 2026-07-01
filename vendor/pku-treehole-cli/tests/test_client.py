"""Client failure contract + pagination, against a fake transport (no network)."""

import pytest

from treehole import endpoints
from treehole.client import TreeholeClient
from treehole.errors import APIError, AuthError, NeedSMSVerification
from treehole.session import Identity


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeCookies:
    def set(self, *a, **k):
        pass

    def get_dict(self):
        return {}


class FakeSession:
    """Returns queued responses in order; records request urls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.headers = {}
        self.cookies = FakeCookies()
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw.get("params")))
        return self._responses.pop(0)


def _ident():
    return Identity(jwt="j", login_uuid="dev1")


def _ok(data):
    return FakeResp(200, {"code": 20000, "success": True, "data": data})


def test_need_sms_raises():
    s = FakeSession([FakeResp(200, {"code": 40002, "message": "请手机短信验证", "success": False})])
    c = TreeholeClient(_ident(), session=s)
    with pytest.raises(NeedSMSVerification):
        c.followed()


def test_non_success_code_raises_apierror():
    s = FakeSession([FakeResp(200, {"code": 41001, "message": "树洞不存在", "success": False})])
    c = TreeholeClient(_ident(), session=s)
    with pytest.raises(APIError) as ei:
        c.hole(1)
    assert ei.value.code == 41001


def test_401_without_relogin_raises_autherror():
    s = FakeSession([FakeResp(401, {})])
    c = TreeholeClient(_ident(), session=s)
    with pytest.raises(AuthError):
        c.users_info()


def test_401_triggers_single_relogin_then_succeeds():
    s = FakeSession([FakeResp(401, {}), _ok({"uid": "x"})])
    calls = {"n": 0}

    def relogin():
        calls["n"] += 1
        return Identity(jwt="fresh", login_uuid="dev1")

    c = TreeholeClient(_ident(), session=s, relogin=relogin)
    assert c.users_info() == {"uid": "x"}
    assert calls["n"] == 1
    assert s.headers["Authorization"] == "Bearer fresh"  # identity re-applied


def test_uuid_header_applied():
    s = FakeSession([_ok({})])
    TreeholeClient(_ident(), session=s)
    assert s.headers["uuid"] == "Web_PKUHOLE_2.0.0_WEB_UUID_dev1"


def test_followed_all_paginates_on_fullness_not_total():
    # `total` is a misleading sentinel; pagination must key on page fullness.
    pages = [
        _ok({"list": [{"pid": i} for i in range(50)], "total": 4}),   # full → continue
        _ok({"list": [{"pid": i} for i in range(50, 75)], "total": 100}),  # partial → stop
    ]
    s = FakeSession(pages)
    c = TreeholeClient(_ident(), session=s)
    holes = c.followed_all(limit=50)
    assert len(holes) == 75
    assert len(s.calls) == 2  # stopped on the partial page, no wasted extra request


def test_search_passes_keyword_to_hole_list():
    s = FakeSession([_ok({"list": [{"pid": 1, "text": "考试周"}], "total": 2})])
    c = TreeholeClient(_ident(), session=s)
    hits = c.search("考试", limit=10).get("list")
    assert hits == [{"pid": 1, "text": "考试周"}]
    _, url, params = s.calls[0]
    assert url == endpoints.HOLE_LIST
    assert params == {"keyword": "考试", "page": 1, "limit": 10}


def test_search_bare_digits_stay_keyword_not_pid():
    # A numeric query searches for holes referencing that number, not an id lookup.
    s = FakeSession([_ok({"list": [], "total": 1})])
    c = TreeholeClient(_ident(), session=s)
    c.search("8282576")
    _, _, params = s.calls[0]
    assert params["keyword"] == "8282576"
    assert "pid" not in params


def test_search_all_paginates_on_fullness():
    pages = [
        _ok({"list": [{"pid": i} for i in range(50)], "total": 4}),       # full → continue
        _ok({"list": [{"pid": i} for i in range(50, 60)], "total": 100}),  # partial → stop
    ]
    s = FakeSession(pages)
    c = TreeholeClient(_ident(), session=s)
    hits = c.search_all("x", limit=50)
    assert len(hits) == 60
    assert len(s.calls) == 2


def test_comments_all_walks_until_partial_page():
    pages = [
        _ok({"list": [{"cid": i} for i in range(50)]}),        # full → continue
        _ok({"list": [{"cid": i} for i in range(50, 70)]}),    # partial → stop
    ]
    s = FakeSession(pages)
    c = TreeholeClient(_ident(), session=s)
    cmts = c.comments_all(123, limit=50)
    assert len(cmts) == 70
    assert len(s.calls) == 2


def test_search_need_sms_raises():
    s = FakeSession([FakeResp(200, {"code": 40002, "message": "请手机短信验证", "success": False})])
    c = TreeholeClient(_ident(), session=s)
    with pytest.raises(NeedSMSVerification):
        c.search("考试")
