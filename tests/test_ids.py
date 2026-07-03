import re

from pypku3b.ids import content_hash


def test_deterministic_and_hex16():
    a = content_hash("_86215_1", "_1476964_1")
    b = content_hash("_86215_1", "_1476964_1")
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{16}", a)


def test_distinct_inputs_distinct_ids():
    assert content_hash("_1_1", "_2_1") != content_hash("_1_1", "_3_1")
    assert content_hash("_1_1", "_2_1") != content_hash("_9_1", "_2_1")


def test_separator_prevents_collision():
    # (a="x", b="yz") must not collide with (a="xy", b="z").
    assert content_hash("x", "yz") != content_hash("xy", "z")
