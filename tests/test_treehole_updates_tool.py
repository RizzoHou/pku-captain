from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tools.treehole_updates import NeedSMSVerification, TreeholeUpdatesTool


@dataclass(frozen=True)
class FakeComment:
    cid: int
    text: str
    name_tag: str
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "text": self.text,
            "name_tag": self.name_tag,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class FakeUpdate:
    pid: str
    old_reply: int
    new_reply: int
    delta: int
    text: str
    new_comments: list[FakeComment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "old_reply": self.old_reply,
            "new_reply": self.new_reply,
            "delta": self.delta,
            "text": self.text,
            "new_comments": [comment.to_dict() for comment in self.new_comments],
        }


class FakeMonitor:
    def __init__(self) -> None:
        self.only: set[str] | None = None

    def check(
        self, *, only: set[str] | None = None, fetch_comments: bool = True
    ) -> list[FakeUpdate]:
        self.only = only
        assert fetch_comments is True
        return [
            FakeUpdate(
                pid="123",
                old_reply=2,
                new_reply=4,
                delta=2,
                text="原洞内容",
                new_comments=[
                    FakeComment(7, "第一条新回复", "洞友", 1717200000),
                    FakeComment(8, "第二条新回复", "洞主", 1717200060),
                ],
            )
        ]


def test_treehole_updates_tool_returns_structured_updates() -> None:
    monitor = FakeMonitor()
    tool = TreeholeUpdatesTool(monitor_factory=lambda *args, **kwargs: monitor)

    result = tool.invoke({"holes": ["123"], "limit": 5})

    assert result.success is True
    assert result.data["status"] == "has_updates"
    assert result.data["unread_count"] == 2
    assert result.data["updates"][0]["pid"] == "123"
    assert result.data["updates"][0]["new_comments"][1]["text"] == "第二条新回复"
    assert monitor.only == {"123"}


def test_treehole_updates_tool_surfaces_sms_verification() -> None:
    def factory(*args: object, **kwargs: object) -> object:
        class SMSMonitor:
            def check(self, **_: object) -> list[object]:
                raise NeedSMSVerification("请手机短信验证")

        return SMSMonitor()

    tool = TreeholeUpdatesTool(monitor_factory=factory)

    result = tool.invoke({})

    assert result.success is True
    assert result.data["status"] == "needs_sms"
    assert result.data["unread_count"] == 0
    assert "短信验证" in result.data["message"]
