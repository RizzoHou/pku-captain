import pytest

from pypku3b.errors import AuthError
from pypku3b.portal import identity_from_payload


def test_identity_maps_camel_to_snake():
    payload = {
        "success": True,
        "name": "张三",
        "studentId": "2500000000",
        "sex": "男",
        "userIdentity": "本科生",
        "department": "信息科学技术学院",
        "studentType": "普通本科生",
        "speciality": "计算机科学与技术",
        "direction": "",
        "politics": "群众",
        "ethnic": "汉族",
        "nativePlace": "北京",
    }
    ident = identity_from_payload(payload)
    assert ident.student_id == "2500000000"
    assert ident.user_identity == "本科生"
    assert ident.native_place == "北京"
    # Empty string -> None.
    assert ident.direction is None


def test_identity_empty_and_null_normalize_to_none():
    payload = {"success": True, "name": "  ", "direction": "null", "sex": None}
    ident = identity_from_payload(payload)
    assert ident.name is None
    assert ident.direction is None
    assert ident.sex is None


def test_identity_unsuccessful_raises():
    with pytest.raises(AuthError):
        identity_from_payload({"success": False, "name": "张三"})
