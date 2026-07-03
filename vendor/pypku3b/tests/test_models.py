from pypku3b.models import Assignment, Attachment, Identity


def test_assignment_to_dict_key_order_matches_pku3b():
    a = Assignment(
        id="deadbeef",
        course_name="计算概论A",
        course_title="计算概论A(25-26学年第1学期)",
        course_id="_86058_1",
        title="大作业",
        deadline_raw="2026年1月11日 星期日 下午11:59",
        deadline_iso="2026-01-11T23:59:00+08:00",
        completed=True,
        last_attempt="尝试 26-1-8 上午11:43",
        descriptions=["desc"],
        attachments=[Attachment("Amazons.docx", "/bbcswebdav/x")],
    )
    d = a.to_dict()
    assert list(d) == [
        "id",
        "course_name",
        "course_title",
        "course_id",
        "title",
        "deadline_raw",
        "deadline_iso",
        "completed",
        "last_attempt",
        "descriptions",
        "attachments",
    ]
    assert d["attachments"] == [{"name": "Amazons.docx", "uri": "/bbcswebdav/x"}]


def test_identity_to_dict_shape():
    ident = Identity(name="张三", student_id="2500000000")
    d = ident.to_dict()
    assert list(d) == [
        "name",
        "student_id",
        "sex",
        "user_identity",
        "department",
        "student_type",
        "speciality",
        "direction",
        "politics",
        "ethnic",
        "native_place",
    ]
    assert d["name"] == "张三"
    assert d["direction"] is None
