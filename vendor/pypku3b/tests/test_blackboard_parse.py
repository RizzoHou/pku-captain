"""Parser tests over small synthetic HTML (no network, no personal data)."""

from pypku3b.blackboard import (
    LIST_CONTENT,
    _course_name,
    _course_title,
    _seed_content_ids,
    parse_announcements,
    parse_attempt,
    parse_content_list,
    parse_course_menu,
    parse_courses,
    parse_deadline_raw,
)

COURSES_HTML = """
<div class="portlet">
  <span class="moduleTitle">当前课程 (Current Semester Courses)</span>
  <ul class="courseListing">
    <li><a href="/x?key=_86058_1,y">25262-CODE: 计算概论A（上）(25-26学年第1学期)</a></li>
    <li><a href="/x?key=_86215_1,y">CODE2: 物理学(25-26学年第1学期)</a></li>
  </ul>
</div>
<div class="portlet">
  <span class="moduleTitle">以前学期课程</span>
  <ul class="courseListing">
    <li><a href="/x?key=_70001_1,y">OLD: 旧课(24-25学年第2学期)</a></li>
  </ul>
</div>
<div class="portlet">
  <span class="moduleTitle">公告</span>
  <ul class="courseListing"><li><a href="/x?key=_99_1,y">not a course listing block</a></li></ul>
</div>
"""


def test_parse_courses():
    courses = parse_courses(COURSES_HTML)
    # The 公告 portlet is skipped (title lacks 课程/Courses).
    assert ("_86058_1", "25262-CODE: 计算概论A（上）(25-26学年第1学期)", True) in courses
    assert ("_86215_1", "CODE2: 物理学(25-26学年第1学期)", True) in courses
    assert ("_70001_1", "OLD: 旧课(24-25学年第2学期)", False) in courses
    assert not any(c[0] == "_99_1" for c in courses)


def test_course_title_and_name():
    long = "25262-CODE: 计算概论A（上）(25-26学年第1学期)"
    assert _course_title(long) == "计算概论A（上）(25-26学年第1学期)"
    # Name truncates at the last ASCII '(', keeping the 全角（上）.
    assert _course_name(_course_title(long)) == "计算概论A（上）"


CONTENT_HTML = """
<ul id="content_listContainer">
  <li>
    <img alt="作业"/>
    <div id="_123_1"><a href="#">第一次作业</a></div>
    <div>
      <div class="vtbegenerated"><p>说明一</p><p>说明二</p></div>
      <ul class="attachments"><li><a href="/bbcswebdav/pid-1/xid-1"> Amazons.docx</a></li></ul>
    </div>
  </li>
  <li>
    <img alt="文件"/>
    <div id="_124_1">课件</div>
    <div><div class="vtbegenerated"></div></div>
  </li>
  <li><img alt="作业"/><div id="_125_1">链接作业</div></li>
</ul>
"""


def test_parse_content_list():
    items = parse_content_list(CONTENT_HTML)
    by_id = {c.id: c for c in items}
    # Third li has only 2 child elements -> skipped.
    assert set(by_id) == {"_123_1", "_124_1"}
    a = by_id["_123_1"]
    assert a.kind == "assignment"
    assert a.title == "第一次作业"
    assert a.has_link is True
    assert a.descriptions == ["说明一", "说明二"]
    assert a.attachments == [("Amazons.docx", "/bbcswebdav/pid-1/xid-1")]
    assert by_id["_124_1"].kind == "document"


def test_parse_course_menu_and_seeds():
    menu_html = """
    <ul id="courseMenuPalette_contents">
      <li><a href="/webapps/blackboard/content/listContent.jsp?course_id=_1_1&content_id=_555_1">课程作业</a></li>
      <li><a href="/webapps/blackboard/execute/announcement?course_id=_1_1">课程通知</a></li>
    </ul>
    """
    menu = parse_course_menu(menu_html)
    assert menu["课程作业"].endswith("content_id=_555_1")
    assert _seed_content_ids(menu) == ["_555_1"]
    assert LIST_CONTENT.endswith("listContent.jsp")


def test_parse_deadline_and_attempt():
    deadline_html = (
        '<span id="assignMeta2">截止日期</span>'
        "<div>  2026年4月4日  星期五  下午11:59  </div>"
    )
    assert parse_deadline_raw(deadline_html) == "2026年4月4日 星期五 下午11:59"
    assert parse_deadline_raw("<div>no meta</div>") is None

    attempt_html = '<h3 id="currentAttempt_label">  尝试 25-9-22 下午12:49 </h3>'
    assert parse_attempt(attempt_html) == "尝试 25-9-22 下午12:49"
    assert parse_attempt("<h3>other</h3>") is None


ANNOUNCEMENT_HTML = """
<div class="container clearfix">
  <h3>物理学(25-26学年第1学期)</h3>
  <h3>Late Policy</h3>
  <div><p><span>发布时间: 2026年4月11日 星期六 下午04时04分00秒 CST</span></p></div>
  <div>发帖者: 计算机学院 曹老师<br>发布至: 物理学</div>
  <div class="vtbegenerated"><p>迟交每天扣十分。</p></div>
  <h3>课堂测验开放</h3>
  <div class="vtbegenerated"><p>本周测验已开放。</p></div>
</div>
"""


def test_parse_announcements_extracts_title_date_body():
    anns = parse_announcements(ANNOUNCEMENT_HTML, "_86215_1", "物理学")
    by_title = {a.title: a for a in anns}
    # The 学期 h3 is filtered out.
    assert "物理学(25-26学年第1学期)" not in by_title
    late = by_title["Late Policy"]
    assert late.time is not None and "2026年4月11日" in late.time
    assert "迟交每天扣十分。" in late.descriptions
    # 发帖者/发布至 metadata is not part of the body.
    assert not any("发帖者" in d for d in late.descriptions)
    assert "课堂测验开放" in by_title


def test_parse_announcements_dedup_by_course_scope():
    # Same page parsed twice under different course ids -> independent ids.
    a1 = parse_announcements(ANNOUNCEMENT_HTML, "_1_1", "物理学")
    a2 = parse_announcements(ANNOUNCEMENT_HTML, "_2_1", "物理学")
    assert {a.id for a in a1}.isdisjoint({a.id for a in a2})
