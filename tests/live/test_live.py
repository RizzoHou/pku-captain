"""Network-backed end-to-end tests, skipped unless ``PYPKU3B_LIVE=1``.

Requires real PKU credentials. Point ``PYPKU3B_SECRETS`` at a dir with
``id``/``password`` (default ``secrets/pku``); optionally ``PYPKU3B_SEED_COOKIES``
at a pku3b ``ua.json`` to reuse an existing Blackboard session and skip OTP.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PYPKU3B_LIVE") != "1", reason="set PYPKU3B_LIVE=1 to run"
)


def _client(tmp_path):
    from pypku3b import Client

    return Client(
        secrets_dir=os.environ.get("PYPKU3B_SECRETS", "secrets/pku"),
        cookie_path=tmp_path / "cookies.json",
        seed_cookie_path=os.environ.get("PYPKU3B_SEED_COOKIES"),
        cache_dir=tmp_path / "cache",
        timeout=120,
    )


def test_identity(tmp_path):
    ident = _client(tmp_path).get_identity()
    assert ident.name
    assert ident.student_id


def test_coursetable(tmp_path):
    table = _client(tmp_path).get_coursetable()
    assert set(table.raw) >= {"course", "success"}


def test_assignments(tmp_path):
    assigns = _client(tmp_path).list_assignments(include_completed=True, all_term=True)
    assert isinstance(assigns, list)
    for a in assigns:
        assert a.course_id and a.title
        if a.deadline_raw:
            assert a.deadline_iso and a.deadline_iso.endswith("+08:00")


def test_announcements(tmp_path):
    anns = _client(tmp_path).list_announcements()
    assert isinstance(anns, list)
