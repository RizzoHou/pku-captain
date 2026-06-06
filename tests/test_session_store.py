"""SessionStore: serialization round-trips, listing/sort, title updates,
delete, and corrupt/missing-file tolerance — all in tmp_path."""

from __future__ import annotations

import json
import re

from src.core.session_store import (
    SessionStore,
    deserialize_messages,
    drop_incomplete_tool_calls,
    serialize_messages,
)
from src.llm.base import ChatMessage, ToolCall


def _sample_messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="你好"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(id="c1", name="clock", arguments={"tz": "CST"}),),
            reasoning_content="thinking",
        ),
        ChatMessage(role="tool", name="clock", tool_call_id="c1", content="noon"),
        ChatMessage(role="assistant", content="现在是中午"),
    ]


def test_serialize_deserialize_roundtrip() -> None:
    msgs = _sample_messages()
    assert deserialize_messages(serialize_messages(msgs)) == msgs


def test_save_load_roundtrip(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.new_id()
    msgs = _sample_messages()
    store.save(
        sid,
        messages=msgs,
        title="标题",
        created_at="2026-06-05T10:00:00+08:00",
        offline=False,
    )
    rec = store.load(sid)
    assert rec is not None
    assert rec["title"] == "标题"
    assert rec["offline"] is False
    assert rec["created_at"] == "2026-06-05T10:00:00+08:00"
    assert "updated_at" in rec
    assert deserialize_messages(rec["messages"]) == msgs


def test_new_id_format_and_unique(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    ids = {store.new_id() for _ in range(50)}
    assert len(ids) == 50  # collision-proof within the same second
    assert all(re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", i) for i in ids)


def test_list_sorted_by_updated_desc(tmp_path) -> None:
    # Write files directly with controlled updated_at so the sort is
    # deterministic (save() stamps now, which would tie within a second).
    directory = tmp_path / "sessions"
    directory.mkdir(parents=True)
    (directory / "old.json").write_text(
        json.dumps(
            {
                "id": "old",
                "title": "Old",
                "updated_at": "2026-06-01T10:00:00+08:00",
                "messages": [],
            }
        ),
        encoding="utf-8",
    )
    (directory / "new.json").write_text(
        json.dumps(
            {
                "id": "new",
                "title": "New",
                "updated_at": "2026-06-05T10:00:00+08:00",
                "messages": [1, 2],
            }
        ),
        encoding="utf-8",
    )
    store = SessionStore(directory)
    listed = store.list_sessions()
    assert [m["id"] for m in listed] == ["new", "old"]
    assert listed[0]["message_count"] == 2


def test_update_title_preserves_messages(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.new_id()
    msgs = _sample_messages()
    store.save(sid, messages=msgs, title="临时", created_at="c", offline=True)
    store.update_title(sid, "最终标题")
    rec = store.load(sid)
    assert rec is not None
    assert rec["title"] == "最终标题"
    assert deserialize_messages(rec["messages"]) == msgs  # messages untouched


def test_update_title_missing_is_noop(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.update_title("does-not-exist", "x")  # must not raise
    assert store.load("does-not-exist") is None


def test_delete(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sid = store.new_id()
    store.save(
        sid,
        messages=[ChatMessage(role="user", content="x")],
        title="t",
        created_at="c",
        offline=False,
    )
    assert store.delete(sid) is True
    assert store.load(sid) is None
    assert store.delete(sid) is False  # already gone


def _aborted_tool_turn() -> list[ChatMessage]:
    """Conversation left dangling by a turn aborted mid tool-dispatch:
    assistant requested two tools but only one result came back."""
    return [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="跑两个工具"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=(
                ToolCall(id="c1", name="clock", arguments={}),
                ToolCall(id="c2", name="memory", arguments={}),
            ),
        ),
        ChatMessage(role="tool", name="clock", tool_call_id="c1", content="noon"),
        # c2 never answered — turn aborted here.
    ]


def test_drop_incomplete_tool_calls_trims_dangling_tail() -> None:
    trimmed = drop_incomplete_tool_calls(_aborted_tool_turn())
    # The dangling assistant + its partial tool result are removed.
    assert [m.role for m in trimmed] == ["system", "user"]
    assert all(not (m.role == "assistant" and m.tool_calls) for m in trimmed)


def test_drop_incomplete_tool_calls_keeps_complete_turn() -> None:
    complete = _sample_messages()  # assistant(tool_calls) fully answered
    assert drop_incomplete_tool_calls(complete) == complete


def test_save_sanitizes_dangling_tool_calls(tmp_path) -> None:
    # An aborted turn must not be persisted as an invalid sequence, else a
    # reopen + follow-up would 400 forever.
    store = SessionStore(tmp_path / "sessions")
    sid = store.new_id()
    store.save(sid, messages=_aborted_tool_turn(), title="t", created_at="c", offline=True)
    rec = store.load(sid)
    assert rec is not None
    restored = deserialize_messages(rec["messages"])
    assert not any(m.role == "assistant" and m.tool_calls for m in restored)
    assert not any(m.role == "tool" for m in restored)


def test_corrupt_and_missing_tolerated(tmp_path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text("{not valid json", encoding="utf-8")
    store = SessionStore(directory)
    assert store.list_sessions() == []  # corrupt file skipped, no crash
    assert store.load("bad") is None
    # entirely missing directory
    assert SessionStore(tmp_path / "nope").list_sessions() == []
