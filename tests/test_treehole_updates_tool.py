from __future__ import annotations

import json
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
                    "pid": "100" if keyword == "考试" else "101",
                    "text": f"{keyword} 命中内容",
                    "reply": 3,
                    "likenum": 8,
                    "timestamp": 1_717_200_000,
                }
            ]
        }

    def search_all(self, keyword: str, *, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append(("search_all", {"keyword": keyword, "limit": limit}))
        return [{"pid": "101", "text": "全部搜索结果"}]

    def hole(self, pid: str) -> dict[str, object]:
        self.calls.append(("hole", pid))
        return {"pid": pid, "text": "原洞内容", "reply": 2, "likenum": 5}

    def comments_all(self, pid: str, *, limit: int = 50) -> list[dict[str, object]]:
        self.calls.append(("comments_all", {"pid": pid, "limit": limit}))
        return [{"cid": 1, "text": "第一条评论", "name_tag": "洞友"}]

    def comments(self, pid: str, *, page: int = 1, limit: int = 25) -> list[dict[str, object]]:
        self.calls.append(("comments", {"pid": pid, "page": page, "limit": limit}))
        return [{"cid": 1, "text": "第一条评论", "name_tag": "洞友"}]


def test_treehole_tool_search_returns_results() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "search", "keyword": "考试", "limit": 7})

    assert result.success is True
    assert result.data["action"] == "search"
    assert result.data["results"][0]["pid"] == "100"
    assert result.data["keywords"] == ["考试"]
    assert client.calls == [("search", {"keyword": "考试", "limit": 7})]


def test_treehole_tool_search_splits_space_keywords_and_caps_terms() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "search", "keyword": "考试 选课 绩点 保研", "limit": 5})

    assert result.success is True
    assert result.data["keywords"] == ["考试", "选课", "绩点"]
    assert result.data["ignored_keywords"] == ["保研"]
    assert client.calls == [
        ("search", {"keyword": "考试", "limit": 5}),
        ("search", {"keyword": "选课", "limit": 5}),
        ("search", {"keyword": "绩点", "limit": 5}),
    ]


def test_treehole_tool_search_ignores_all_pagination() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "search", "keyword": "考试", "limit": 5, "all": True})

    assert result.success is True
    assert client.calls == [("search", {"keyword": "考试", "limit": 5})]


def test_treehole_tool_search_can_filter_category() -> None:
    class CategoryClient(FakeTreeholeClient):
        def search(self, keyword: str, *, limit: int = 25) -> dict[str, object]:
            self.calls.append(("search", {"keyword": keyword, "limit": limit}))
            return {
                "list": [
                    {
                        "pid": "100",
                        "text": "期末考试 课程 作业",
                        "reply": 2,
                        "likenum": 3,
                    },
                    {
                        "pid": "101",
                        "text": "食堂 校园生活",
                        "reply": 99,
                        "likenum": 88,
                    },
                ]
            }

    client = CategoryClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "search", "keyword": "考试", "category": "课程/考试"})

    assert [item["pid"] for item in result.data["results"]] == ["100"]


def test_treehole_tool_fetch_returns_hole_and_comments() -> None:
    client = FakeTreeholeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "fetch", "pid": "#100", "limit": 20})

    assert result.success is True
    assert result.data["action"] == "fetch"
    assert result.data["pid"] == "100"
    assert result.data["hole"]["text"] == "原洞内容"
    assert result.data["comments"][0]["text"] == "第一条评论"
    assert result.data["returned_comments"] == 1
    assert client.calls == [
        ("hole", "100"),
        ("comments", {"pid": "100", "page": 1, "limit": 20}),
    ]


def test_treehole_tool_fetch_keeps_large_comments_under_budget() -> None:
    class LargeClient(FakeTreeholeClient):
        def hole(self, pid: str) -> dict[str, object]:
            self.calls.append(("hole", pid))
            return {"pid": pid, "text": "原洞内容" * 1000, "reply": 100, "likenum": 5}

        def comments(self, pid: str, *, page: int = 1, limit: int = 25) -> list[dict[str, object]]:
            self.calls.append(("comments", {"pid": pid, "page": page, "limit": limit}))
            return [
                {"cid": cid, "text": "很长的评论" * 1000, "name_tag": "洞友"}
                for cid in range(1, limit + 1)
            ]

    client = LargeClient()
    tool = TreeholeTool(client_factory=lambda *args, **kwargs: client)

    result = tool.invoke({"action": "fetch", "pid": "100", "limit": 20})

    assert result.success is True
    assert result.data["truncated"] is True
    assert len(json.dumps(result.data, ensure_ascii=False)) <= 6500


def test_treehole_tool_surfaces_sms_verification() -> None:
    class SMSClient:
        def search(self, *_: object, **__: object) -> dict[str, object]:
            raise NeedSMSVerification("请手机短信验证")

    tool = TreeholeTool(client_factory=lambda *args, **kwargs: SMSClient())

    result = tool.invoke({"action": "search", "keyword": "考试"})

    assert result.success is True
    assert result.data["status"] == "needs_sms"
    assert "短信验证" in result.data["message"]
