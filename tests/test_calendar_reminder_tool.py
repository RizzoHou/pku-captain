"""Unit coverage for CalendarReminderTool.

All osascript calls are mocked — the tests never touch the real macOS Calendar.
``sys.platform`` is monkeypatched too, so assertions run deterministically on
non-macOS CI as well.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

import src.tools.calendar_reminder as calendar_reminder
from src.tools.calendar_reminder import CalendarReminderTool, _parse_local


class _FakeRun:
    """Records osascript invocations and returns a canned process result."""

    def __init__(self, returncode: int = 0, stdout: str = "ok\n", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> types.SimpleNamespace:
        self.calls.append({"argv": argv, "kwargs": kwargs})
        return types.SimpleNamespace(
            returncode=self.returncode, stdout=self.stdout, stderr=self.stderr
        )


@pytest.fixture
def on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_reminder.sys, "platform", "darwin")


def _install_run(monkeypatch: pytest.MonkeyPatch, fake: _FakeRun) -> None:
    monkeypatch.setattr(calendar_reminder.subprocess, "run", fake)


def test_adds_events_and_builds_argv(monkeypatch: pytest.MonkeyPatch, on_macos: None) -> None:
    fake = _FakeRun()
    _install_run(monkeypatch, fake)
    iso = "2026-06-06T23:59:00"

    result = CalendarReminderTool().invoke(
        {"items": [{"title": "作业一", "deadline_iso": iso, "notes": "课程：测试"}]}
    )

    when = _parse_local(iso)  # tz-agnostic: mirrors the tool's local conversion
    assert result.success is True
    assert result.data["calendar"] == "PKU Captain"
    assert result.data["added"] == [{"title": "作业一", "when": when.strftime("%Y-%m-%d %H:%M")}]
    assert result.data["failed"] == []

    assert len(fake.calls) == 1
    argv = fake.calls[0]["argv"]
    assert argv[:4] == ["osascript", "-", "PKU Captain", "作业一"]
    assert argv[4:9] == [
        str(when.year),
        str(when.month),
        str(when.day),
        str(when.hour),
        str(when.minute),
    ]
    assert argv[9] == "1440"  # default alarm = one day before
    assert argv[10] == "课程：测试"
    # The AppleScript itself is piped on stdin, not passed as an arg.
    assert "make new event" in fake.calls[0]["kwargs"]["input"]


def test_batch_makes_one_call_per_item(monkeypatch: pytest.MonkeyPatch, on_macos: None) -> None:
    fake = _FakeRun()
    _install_run(monkeypatch, fake)

    result = CalendarReminderTool().invoke(
        {
            "items": [
                {"title": "A", "deadline_iso": "2026-06-06T10:00:00"},
                {"title": "B", "deadline_iso": "2026-06-07T10:00:00"},
                {"title": "C", "deadline_iso": "2026-06-08T10:00:00"},
            ],
            "calendar_name": "Custom",
            "alarm_minutes_before": 60,
        }
    )

    assert result.success is True
    assert len(result.data["added"]) == 3
    assert len(fake.calls) == 3
    assert all(call["argv"][2] == "Custom" for call in fake.calls)
    assert all(call["argv"][9] == "60" for call in fake.calls)


def test_non_macos_returns_error_without_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_reminder.sys, "platform", "linux")
    fake = _FakeRun()
    _install_run(monkeypatch, fake)

    result = CalendarReminderTool().invoke(
        {"items": [{"title": "A", "deadline_iso": "2026-06-06T10:00:00"}]}
    )

    assert result.success is False
    assert "macOS" in (result.error or "")
    assert fake.calls == []


def test_empty_items_rejected(monkeypatch: pytest.MonkeyPatch, on_macos: None) -> None:
    fake = _FakeRun()
    _install_run(monkeypatch, fake)
    assert CalendarReminderTool().invoke({"items": []}).success is False
    assert CalendarReminderTool().invoke({}).success is False
    assert fake.calls == []


def test_invalid_deadline_goes_to_failed(monkeypatch: pytest.MonkeyPatch, on_macos: None) -> None:
    fake = _FakeRun()
    _install_run(monkeypatch, fake)

    result = CalendarReminderTool().invoke(
        {
            "items": [
                {"title": "bad", "deadline_iso": "not-a-date"},
                {"title": "good", "deadline_iso": "2026-06-06T10:00:00"},
                {"title": "missing"},
            ]
        }
    )

    assert result.success is True  # at least one added
    assert [a["title"] for a in result.data["added"]] == ["good"]
    failed_titles = {f["title"] for f in result.data["failed"]}
    assert failed_titles == {"bad", "missing"}
    assert len(fake.calls) == 1  # only the valid item reached osascript


def test_not_authorized_is_actionable_and_short_circuits(
    monkeypatch: pytest.MonkeyPatch, on_macos: None
) -> None:
    fake = _FakeRun(
        returncode=1,
        stdout="",
        stderr="execution error: Not authorized to send Apple events to Calendar. (-1743)",
    )
    _install_run(monkeypatch, fake)

    result = CalendarReminderTool().invoke(
        {
            "items": [
                {"title": "A", "deadline_iso": "2026-06-06T10:00:00"},
                {"title": "B", "deadline_iso": "2026-06-07T10:00:00"},
            ]
        }
    )

    assert result.success is False
    assert len(result.data["added"]) == 0
    assert len(result.data["failed"]) == 2  # second item folded in without re-running
    assert len(fake.calls) == 1  # short-circuited after the permission denial
    assert "自动化" in (result.error or "")
