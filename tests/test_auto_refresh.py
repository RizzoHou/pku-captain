from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.auto_refresh import (
    AutoRefreshSettings,
    AutoRefreshSettingsStore,
    DashboardChange,
    DashboardDigest,
    MacOSNotifier,
    detect_dashboard_changes,
)
from src.llm.base import ChatResponse


def test_settings_store_defaults_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = AutoRefreshSettingsStore(path)

    assert store.load() == AutoRefreshSettings()

    store.save(
        AutoRefreshSettings(enabled=False, interval_seconds=600, notify_enabled=False)
    )

    assert store.load() == AutoRefreshSettings(
        enabled=False, interval_seconds=600, notify_enabled=False
    )


def test_detect_assignment_add_and_deadline_change() -> None:
    previous = {
        "assignments": [
            {
                "id": "a1",
                "course_name": "程序设计实习",
                "title": "作业一",
                "deadline_iso": "2026-06-01T23:59:00",
            }
        ]
    }
    current = {
        "assignments": [
            {
                "id": "a1",
                "course_name": "程序设计实习",
                "title": "作业一",
                "deadline_iso": "2026-06-02T23:59:00",
                "deadline_raw": "6月2日 23:59",
            },
            {
                "id": "a2",
                "course_name": "人工智能基础",
                "title": "搜索作业",
                "deadline_iso": "2026-06-10T23:59:00",
            },
        ]
    }

    changes = detect_dashboard_changes("pku3b_assignments", previous, current)

    assert [(c.kind, c.title) for c in changes] == [
        ("截止时间变化", "作业一"),
        ("新增", "搜索作业"),
    ]


def test_detect_added_announcements() -> None:
    announcement_changes = detect_dashboard_changes(
        "pku3b_announcements",
        {"announcements": [{"id": "old", "course": "C", "title": "旧通知"}]},
        {
            "announcements": [
                {"id": "old", "course": "C", "title": "旧通知"},
                {"id": "new", "course": "C", "title": "新通知"},
            ]
        },
    )

    assert [(c.source, c.title) for c in announcement_changes] == [("课程通知", "新通知")]


def test_digest_uses_llm_and_falls_back_on_error() -> None:
    changes = [DashboardChange("课程通知", "新增", "期末安排", "程序设计实习")]

    class GoodLLM:
        def chat(self, messages, tools=None):  # noqa: ANN001
            return ChatResponse(text="程序设计实习发布期末安排，请查看。")

    class BadLLM:
        def chat(self, messages, tools=None):  # noqa: ANN001
            raise RuntimeError("boom")

    assert DashboardDigest(GoodLLM()).summarize(changes) == "程序设计实习发布期末安排，请查看。"
    assert "Captain 发现 1 条新变化" in DashboardDigest(BadLLM()).summarize(changes)


def test_macos_notifier_invokes_osascript_and_ignores_other_platforms() -> None:
    calls = []

    def runner(cmd, **kwargs):  # noqa: ANN001
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    notifier = MacOSNotifier(runner=runner, platform_name="darwin")

    assert notifier.notify("有新通知")["ok"] is True
    assert calls[0][0][:2] == ["osascript", "-"]
    assert calls[0][0][-1] == "有新通知"
    assert "display notification" in calls[0][1]["input"]

    calls.clear()
    assert MacOSNotifier(runner=runner, platform_name="linux").notify("x")["ok"] is False
    assert calls == []
