from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tools.treehole_updates import NeedSMSVerification, TreeholeTool, TreeholeUpdatesTool


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


class FakeTreeholeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def search(self, keyword: str, *, limit: int = 25) -> dict[str, object]:
        self.calls.append(("search", {"keyword": keyword, "limit": limit}))
        return {
            "list": [
                {
                    "pid": "100",
                    "text": "关键词命中内容",
                    "reply": 3,
                    "likenum": 8,
                }
            ]
        }

    def search_all(self, keyword: str, *, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append(("search_all", {"keyword": keyword, "limit": limit}))
        return [{"pid": "101", "text": "全部搜索结果"}]

    def hole(self, pid: str) -> dict[str, object]:
        self.calls.append(("hole", pid))
        return {"pid": pid, "text": "原洞内容", "reply": 2}

    def comments_all(self, pid: str, *, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append(("comments_all", {"pid": pid, "limit": limit}))
        return [{"cid": 1, "text": "第一条评论", "name_tag": "洞友"}]


def test_treehole_tool_search_returns_results() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "search", "keyword": "考试", "limit": 7})

    assert result.success is True
    assert result.data["action"] == "search"
    assert result.data["results"][0]["pid"] == "100"
    assert client.calls == [("search", {"keyword": "考试", "limit": 7})]


def test_treehole_tool_fetch_returns_hole_and_comments() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "fetch", "pid": "#100", "limit": 20})

    assert result.success is True
    assert result.data["action"] == "fetch"
    assert result.data["pid"] == "100"
    assert result.data["hole"]["text"] == "原洞内容"
    assert result.data["comments"][0]["text"] == "第一条评论"
    assert client.calls == [
        ("hole", "100"),
        ("comments_all", {"pid": "100", "limit": 20}),
    ]


def test_treehole_tool_surfaces_sms_verification() -> None:
    class SMSClient:
        def search(self, *_: object, **__: object) -> dict[str, object]:
            raise NeedSMSVerification("请手机短信验证")

    tool = TreeholeTool(client_factory=lambda *args, **kwargs: SMSClient())

    result = tool.invoke({"action": "search", "keyword": "考试"})

    assert result.success is True
    assert result.data["status"] == "needs_sms"
    assert "短信验证" in result.data["message"]
