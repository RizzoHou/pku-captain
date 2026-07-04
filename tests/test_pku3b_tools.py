"""In-process pku3b Tool wrappers over a fake ``pypku3b.Client``.

Exercises the assignment/announcement/coursetable output shapes, the
client_factory seam, error -> ToolResult mapping, credential redaction, and the
OTP hint — all without touching the network or the vendored client internals.
"""

from __future__ import annotations

from pypku3b import Announcement, Assignment, Attachment, CourseTable, Identity  # noqa: F401
from pypku3b.errors import AuthError, NeedOTP

from src.tools.pku3b_announcements import (
    PKU3bAnnouncementsTool,
    _posted_at,
    _stable_id,
    _to_record,
)
from src.tools.pku3b_assignments import PKU3bAssignmentsTool
from src.tools.pku3b_coursetable import PKU3bCourseTableTool


class FakeClient:
    def __init__(self, *, assignments=None, announcements=None, coursetable=None, error=None):
        self.assignments = assignments or []
        self.announcements = announcements or []
        self.coursetable = coursetable
        self.error = error
        self.calls: dict = {}

    def list_assignments(self, *, include_completed=False):
        self.calls["include_completed"] = include_completed
        if self.error:
            raise self.error
        return self.assignments

    def list_announcements(self, *, all_term=False, force=False):
        self.calls["all_term"] = all_term
        if self.error:
            raise self.error
        return self.announcements

    def get_coursetable(self, *, force=False, otp_code=""):
        self.calls["otp_code"] = otp_code
        if self.error:
            raise self.error
        return self.coursetable


def _factory(client):
    def make(**_kwargs):
        return client

    return make


_BB = "https://course.pku.edu.cn/webapps/blackboard/content/"
_LIST_CONTENT_URL = _BB + "listContent.jsp?course_id="
_LAUNCH_LINK_URL = _BB + "launchLink.jsp?course_id="
_COURSE_NAME = (
    "线性代数A(主)<br>上课信息：1-15周 每周 理教203  教师：高峡 "
    "备注：习题课<br>考试信息：20260624"
)


def _secrets(tmp_path, password="P@ssw0rd!"):
    (tmp_path / "id").write_text("2300010000")
    (tmp_path / "password").write_text(password)
    return tmp_path


# -- assignments ------------------------------------------------------------


def test_assignments_output_shape(tmp_path):
    a = Assignment(
        id="deadbeef",
        course_name="计算概论A",
        course_title="计算概论A(25-26学年第1学期)",
        course_id="_86058_1",
        title="大作业",
        deadline_raw="2026年1月11日 星期日 下午11:59",
        deadline_iso="2026-01-11T23:59:00+08:00",
        completed=True,
        last_attempt="尝试 26-1-8",
        descriptions=["desc"],
        attachments=[Attachment("Amazons.docx", "/bbcswebdav/x")],
        content_id="_1476964_1",
        course_url=_LIST_CONTENT_URL + "_86058_1",
    )
    client = FakeClient(assignments=[a])
    tool = PKU3bAssignmentsTool(secrets_dir=tmp_path, client_factory=_factory(client))

    result = tool.invoke({"include_completed": True})

    assert result.success
    assert client.calls["include_completed"] is True
    rec = result.data["assignments"][0]
    assert rec["id"] == "deadbeef"
    assert rec["deadline_iso"] == "2026-01-11T23:59:00+08:00"
    assert rec["attachments"] == [{"name": "Amazons.docx", "uri": "/bbcswebdav/x"}]
    assert rec["blackboard_content_id"] == "_1476964_1"
    assert rec["url"].endswith("course_id=_86058_1")
    assert "content_id=_1476964_1" in rec["submit_url"]
    assert "mode=view" in rec["submit_url"]


def test_assignments_error_is_redacted(tmp_path):
    _secrets(tmp_path, password="P@ssw0rd!")
    client = FakeClient(error=AuthError("login failed for user with P@ssw0rd!"))
    tool = PKU3bAssignmentsTool(secrets_dir=tmp_path, client_factory=_factory(client))

    result = tool.invoke({})

    assert result.success is False
    assert "P@ssw0rd!" not in result.error
    assert "***REDACTED***" in result.error


# -- announcements ----------------------------------------------------------


def _ann(idx, course, title, aid, *, posted=None, date=None, body=""):
    return Announcement(
        id=aid,
        index=idx,
        course=course,
        course_id="_1_1",
        title=title,
        posted_time=posted,
        posted_date=date,
        body=body,
        descriptions=body.splitlines() if body else [],
        course_url=_LAUNCH_LINK_URL + "_1_1",
    )


def test_announcements_list_shape_with_inline_dates(tmp_path):
    anns = [
        _ann(1, "程设", "期末考试地点通知", "aaa",
             posted="发布时间: 2026年6月25日 星期四 下午10时12分24秒 CST",
             date="2026-06-25", body="考场安排如下"),
        _ann(2, "高数", "习题课调整", "bbb"),
    ]
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path, client_factory=_factory(FakeClient(announcements=anns))
    )

    result = tool.invoke({})

    assert result.success
    data = result.data
    assert data["count"] == 2
    assert data["total_reported"] == 2
    first = data["announcements"][0]
    # The exposed id is now the content-stable id, not pypku3b's positional a.id.
    assert first["id"] == _stable_id(anns[0])
    assert first["id"] != "aaa"
    assert first["posted_date"] == "2026-06-25"
    # posted_at strips the 发布时间: label.
    assert first["posted_at"].startswith("2026年6月25日")
    assert first["url"].endswith("course_id=_1_1")
    assert data["announcements"][1]["posted_date"] is None


def test_announcements_course_filter_and_limit(tmp_path):
    anns = [
        _ann(1, "程序设计实习", "通知一", "a"),
        _ann(2, "高等数学", "通知二", "b"),
        _ann(3, "程序设计实习", "通知三", "c"),
    ]
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path, client_factory=_factory(FakeClient(announcements=anns))
    )

    result = tool.invoke({"course": "程序设计", "limit": 1})

    assert result.success
    assert result.data["total_reported"] == 3
    assert result.data["count"] == 1
    assert result.data["announcements"][0]["course"] == "程序设计实习"


def test_announcement_detail_mode(tmp_path):
    anns = [
        _ann(1, "程设", "期末通知", "aaa",
             posted="发布时间: 2026年6月25日 星期四 下午10时12分24秒 CST",
             body="第一行\n第二行"),
    ]
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path, client_factory=_factory(FakeClient(announcements=anns))
    )

    result = tool.invoke({"announcement_id": "aaa"})

    assert result.success
    ann = result.data["announcement"]
    assert ann["title"] == "期末通知"
    assert ann["posted_at"].startswith("2026年6月25日")
    assert ann["body"] == "第一行\n第二行"


# The captain saw a 历史通知 whose 标题 was a body snippet and whose 发布时间 was
# the *entire body* — pypku3b's no-h3 fallback branch puts the announcement body
# in the time slot. _posted_at must reject that so the body never masquerades as
# a posted time (the UI already omits 发布时间 when posted_at is falsy).
_BODY_AS_TIME = (
    "请组长以小组为单位，6月6日(周六)23:59前将下述大作业项目阶段性进展材料邮件"
    "(录屏视频如过大，可以发送网盘链接)发送各自程设大作业小组负责助教:"
)


def test_posted_at_rejects_body_masquerading_as_time():
    # Marker-less long free-text blob (the mis-parsed body) -> dropped.
    assert _posted_at(_BODY_AS_TIME) is None
    # Genuine 发布时间-marked line -> kept, label stripped.
    assert _posted_at("发布时间: 2026年6月25日 星期四 下午10时12分24秒 CST").startswith(
        "2026年6月25日"
    )
    # A short bare date line (no label) is a plausible time -> kept.
    assert _posted_at("2026年6月1日") == "2026年6月1日"
    # Empty / whitespace / None -> None.
    assert _posted_at(None) is None
    assert _posted_at("   ") is None


def test_announcement_detail_drops_body_posted_time(tmp_path):
    # A fallback-parsed announcement: 20-char snippet title, body dumped into
    # posted_time, no real posted_date. Detail must NOT surface the body as time.
    snippet_title = _BODY_AS_TIME[:20] + "..."
    anns = [
        _ann(1, "程序设计实习", snippet_title, "aaa",
             posted=_BODY_AS_TIME, date=None, body=_BODY_AS_TIME),
    ]
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path, client_factory=_factory(FakeClient(announcements=anns))
    )

    detail = tool.invoke({"announcement_id": _stable_id(anns[0])})
    assert detail.success
    ann = detail.data["announcement"]
    assert ann["posted_at"] is None  # body no longer leaks into 发布时间
    assert ann["body"] == _BODY_AS_TIME  # body still available

    listing = tool.invoke({})
    assert listing.success
    assert listing.data["announcements"][0]["posted_at"] is None


def test_announcement_detail_not_found(tmp_path):
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path,
        client_factory=_factory(FakeClient(announcements=[_ann(1, "程设", "x", "aaa")])),
    )

    result = tool.invoke({"announcement_id": "zzz"})

    assert result.success is False
    assert "not found" in result.error


def test_announcement_detail_retries_all_term_for_history_ids(tmp_path):
    # 历史通知 ids outlive the current-term list after a term rotation; detail
    # mode must retry across all terms before reporting not-found.
    old = _ann(1, "程设", "上学期通知", "old-id", body="老通知正文")

    class TermFakeClient(FakeClient):
        def list_announcements(self, *, all_term=False, force=False):
            self.calls.setdefault("all_term_seq", []).append(all_term)
            return [old] if all_term else []

    client = TermFakeClient()
    tool = PKU3bAnnouncementsTool(secrets_dir=tmp_path, client_factory=_factory(client))

    result = tool.invoke({"announcement_id": "old-id"})

    assert result.success
    assert result.data["announcement"]["body"] == "老通知正文"
    assert client.calls["all_term_seq"] == [False, True]


def test_announcement_list_mode_never_retries_all_term(tmp_path):
    class CountingClient(FakeClient):
        def list_announcements(self, *, all_term=False, force=False):
            self.calls.setdefault("all_term_seq", []).append(all_term)
            return []

    client = CountingClient()
    tool = PKU3bAnnouncementsTool(secrets_dir=tmp_path, client_factory=_factory(client))

    result = tool.invoke({})

    assert result.success
    assert client.calls["all_term_seq"] == [False]


def test_announcement_stable_id_is_content_determined(tmp_path):
    # Equal (course_id, title) → equal id regardless of scrape position or
    # pypku3b's positional a.id; a different title → a different id.
    a1 = _ann(1, "程设", "期末通知", "pos-1", date="2026-06-25")
    a2 = _ann(7, "程设", "期末通知", "pos-2", date="2026-06-25")
    assert _to_record(a1)["id"] == _to_record(a2)["id"]

    other_title = _ann(1, "程设", "别的通知", "pos-3", date="2026-06-25")
    assert _to_record(a1)["id"] != _to_record(other_title)["id"]


def test_announcement_stable_id_ignores_date_and_normalizes_title(tmp_path):
    # posted_date is intermittent across scrapes, so it is NOT part of the id:
    # the same (course_id, title) yields the same id whether the date is present,
    # absent, or different between scrapes.
    dated = _ann(1, "程设", "期末通知", "pos-1", date="2026-06-25")
    other_date = _ann(1, "程设", "期末通知", "pos-2", date="2026-06-26")
    no_date = _ann(1, "程设", "期末通知", "pos-3")
    assert _stable_id(dated) == _stable_id(other_date) == _stable_id(no_date)

    # Title whitespace is normalized (strip ends, collapse internal runs to one
    # space) so trivial render differences don't flip the hash.
    padded = _ann(1, "程设", "  期末通知 ", "pos-4")  # leading/trailing stripped
    assert _stable_id(padded) == _stable_id(no_date)

    one_space = _ann(1, "程设", "assignment 3 通知", "pos-5")
    many_space = _ann(1, "程设", " assignment   3\t通知 ", "pos-6")  # runs collapse
    assert _stable_id(one_space) == _stable_id(many_space)


def test_announcement_detail_resolves_by_stable_id_after_reorder(tmp_path):
    # The real bug: a course posts/deletes an announcement, so every later row's
    # positional index (and thus pypku3b's a.id) shifts. The stable id the
    # dashboard stored must still resolve to detail on the re-listed set.
    earlier = _ann(1, "程设", "期末考试地点通知", "pos-old",
                   date="2026-06-25", body="考场安排如下")
    stored_id = _stable_id(earlier)  # what the dashboard persisted earlier

    # Later scrape: same announcement now at index 3, positional id changed.
    shifted = _ann(3, "程设", "期末考试地点通知", "pos-new",
                   date="2026-06-25", body="考场安排如下")
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path,
        client_factory=_factory(FakeClient(announcements=[shifted])),
    )

    result = tool.invoke({"announcement_id": stored_id})

    assert result.success
    ann = result.data["announcement"]
    assert ann["body"] == "考场安排如下"
    # detail echoes the same stable id the caller queried
    assert ann["id"] == stored_id


def test_announcement_detail_resolves_across_date_drift(tmp_path):
    # THE live bug this task fixes: pypku3b drops posted_date for ~half of
    # announcements depending on how the page renders, and per-course scrape is
    # TTL-cached, so the store-time scrape and a later show-time re-scrape are
    # independent and can observe different dates. The id the dashboard stored
    # (captured WITH a date) must still resolve to detail when the same
    # announcement is re-listed WITHOUT a date, or with a different one. This
    # fails under the old (course_id, title, date) hash and passes under the
    # date-free hash.
    dated = _ann(1, "程设", "期末考试地点通知", "pos-a",
                 posted="发布时间: 2026年6月25日 星期四 下午10时12分24秒 CST",
                 date="2026-06-25", body="考场安排如下")
    stored_id = _to_record(dated)["id"]  # what the dashboard persisted earlier

    drifts = [
        _ann(3, "程设", "期末考试地点通知", "pos-b", body="考场安排如下"),  # date dropped
        _ann(2, "程设", "期末考试地点通知", "pos-c",  # different date on re-scrape
             date="2026-06-26", body="考场安排如下"),
    ]
    for variant in drifts:
        tool = PKU3bAnnouncementsTool(
            secrets_dir=tmp_path,
            client_factory=_factory(FakeClient(announcements=[variant])),
        )
        result = tool.invoke({"announcement_id": stored_id})
        assert result.success, f"date-drift variant {variant.posted_date!r} failed"
        assert result.data["announcement"]["body"] == "考场安排如下"
        # detail echoes the same stable id the caller queried
        assert result.data["announcement"]["id"] == stored_id


def test_announcement_detail_resolves_legacy_positional_id(tmp_path):
    # Dual-match: a legacy positional id that has NOT yet drifted still resolves
    # (migration window), even though the tool now exposes stable ids.
    ann = _ann(1, "程设", "期末通知", "legacy-pos-id", body="正文")
    tool = PKU3bAnnouncementsTool(
        secrets_dir=tmp_path,
        client_factory=_factory(FakeClient(announcements=[ann])),
    )

    result = tool.invoke({"announcement_id": "legacy-pos-id"})

    assert result.success
    assert result.data["announcement"]["body"] == "正文"
    # even when queried by the legacy id, the returned id is the stable one
    assert result.data["announcement"]["id"] == _stable_id(ann)


# -- coursetable ------------------------------------------------------------


def test_coursetable_parses_blocks(tmp_path):
    raw = {
        "success": True,
        "course": [
            {"mon": {"courseName": _COURSE_NAME}},
            {"mon": {"courseName": _COURSE_NAME}},
        ],
    }
    table = CourseTable(term="25-26-2", raw=raw)
    tool = PKU3bCourseTableTool(
        secrets_dir=tmp_path, client_factory=_factory(FakeClient(coursetable=table))
    )

    result = tool.invoke({})

    assert result.success
    assert result.data["raw"] == raw
    mon_blocks = [b for b in result.data["blocks"] if b["day_key"] == "mon"]
    assert len(mon_blocks) == 1  # two identical adjacent slots merge
    block = mon_blocks[0]
    assert block["title"] == "线性代数A"
    assert block["start_slot"] == 1 and block["end_slot"] == 2
    assert "教师：高峡" in block["detail"]


def test_coursetable_otp_hint(tmp_path):
    client = FakeClient(error=NeedOTP("otp required"))
    tool = PKU3bCourseTableTool(secrets_dir=tmp_path, client_factory=_factory(client))

    result = tool.invoke({})

    assert result.success is False
    assert "OTP" in result.error and "仪表盘" in result.error


def test_coursetable_passes_otp_code(tmp_path):
    table = CourseTable(term="25-26-2", raw={"success": True, "course": []})
    client = FakeClient(coursetable=table)
    tool = PKU3bCourseTableTool(secrets_dir=tmp_path, client_factory=_factory(client))

    tool.invoke({"otp_code": "123456"})

    assert client.calls["otp_code"] == "123456"
