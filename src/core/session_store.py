"""SessionStore — persist chat sessions to disk so conversations survive
restarts and can be reopened.

Each session is one JSON file at ``data/sessions/<id>.json`` holding the
full message history (faithful `asdict` of every `ChatMessage`, including
`tool_calls` and `reasoning_content`) plus metadata. A `threading.Lock`
guards every load/modify/write so the async titler callback (which runs on
a `QThreadPool` thread) cannot interleave a write with the GUI thread's
auto-save.

Serialization mirrors the CLI `/save` dump (`src/cli.py`): plain
`asdict(msg)` per message. `deserialize_messages` rebuilds the frozen
`ChatMessage` / `ToolCall` dataclasses, rebuilding the flattened
`tool_calls` list back into the `tuple[ToolCall, ...]` the type expects.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..llm.base import ChatMessage, ToolCall

_TZ = ZoneInfo("Asia/Shanghai")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SESSIONS_DIR = _REPO_ROOT / "data" / "sessions"


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def serialize_messages(messages: Iterable[ChatMessage]) -> list[dict[str, Any]]:
    """Dump messages to JSON-safe dicts (same shape as the CLI `/save`).

    A multimodal user message (doc_read page images, `content` is a list of
    parts) is collapsed to its text label so the saved file stays small — base64
    page images would bloat it by megabytes. The trade-off: a reopened session
    shows the label, not the raw pages, so an image-grounded follow-up after a
    reload sees text rather than the pages (v1 limitation).
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        d = asdict(m)
        d["content"] = _content_for_storage(d.get("content"))
        out.append(d)
    return out


def _content_for_storage(content: Any) -> Any:
    """Collapse a multimodal `content` list to its text label for persistence."""
    if not isinstance(content, list):
        return content
    texts = [
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    label = " ".join(t for t in texts if t).strip()
    images = sum(
        1
        for part in content
        if isinstance(part, dict) and part.get("type") == "image_url"
    )
    return label or (f"[文档页面图片 ×{images}]" if images else "")


def drop_incomplete_tool_calls(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Trim a trailing assistant whose `tool_calls` aren't all answered.

    A turn that aborts mid tool-dispatch — an unregistered/hallucinated tool
    name (`tools.get` KeyError), an `invoke()` that raises instead of
    returning a failed `ToolResult`, or a force-close during a slow
    subprocess/network tool — leaves the conversation ending in
    `assistant(tool_calls=...)` with some or all tool results missing.
    Persisting that and later appending a user message makes DeepSeek 400
    (the tool_calls-without-matching-responses invariant). Drop the
    offending assistant and any partial results so the saved/restored
    history stays valid. A complete turn (every call answered) is untouched.
    """
    last_asst: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "assistant" and messages[i].tool_calls:
            last_asst = i
            break
    if last_asst is None:
        return list(messages)
    needed = {c.id for c in messages[last_asst].tool_calls}
    answered = {
        m.tool_call_id for m in messages[last_asst + 1 :] if m.role == "tool"
    }
    if needed <= answered:
        return list(messages)
    return list(messages[:last_asst])


def deserialize_messages(raw: Iterable[dict[str, Any]]) -> list[ChatMessage]:
    """Rebuild `ChatMessage` objects from stored dicts.

    Tolerant of older/partial files: every field is read with `.get` and a
    default, and `tool_calls` is rebuilt into a tuple of `ToolCall`.
    """
    messages: list[ChatMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_calls = tuple(
            ToolCall(
                id=str(c.get("id", "")),
                name=str(c.get("name", "")),
                arguments=dict(c.get("arguments") or {}),
            )
            for c in (item.get("tool_calls") or [])
            if isinstance(c, dict)
        )
        messages.append(
            ChatMessage(
                role=item.get("role", "user"),
                content=item.get("content") or "",
                name=item.get("name"),
                tool_call_id=item.get("tool_call_id"),
                tool_calls=tool_calls,
                reasoning_content=item.get("reasoning_content"),
            )
        )
    return messages


class SessionStore:
    """One-JSON-file-per-session store; thread-safe.

    Every public method takes the lock for the whole
    read/modify/write cycle, so the GUI-thread auto-save and the worker-pool
    title update cannot corrupt a file by interleaving.
    """

    def __init__(self, directory: Path | str = _DEFAULT_SESSIONS_DIR) -> None:
        self._dir = Path(directory)
        self._lock = threading.Lock()

    def new_id(self) -> str:
        """Sortable, collision-proof id: timestamp + short random suffix.

        The timestamp gives chronological filenames; the hex suffix keeps
        two New-Chat clicks within the same second from colliding.
        """
        stamp = datetime.now(_TZ).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{uuid.uuid4().hex[:6]}"

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def save(
        self,
        session_id: str,
        *,
        messages: Iterable[ChatMessage],
        title: str,
        created_at: str,
        offline: bool,
    ) -> None:
        """Write the whole session through to disk (overwrites).

        Trims a dangling tool-call tail (from a turn aborted mid-dispatch) so
        the persisted history is always a valid OpenAI/DeepSeek sequence.
        """
        clean = drop_incomplete_tool_calls(list(messages))
        payload = {
            "id": session_id,
            "title": title,
            "created_at": created_at,
            "updated_at": _now_iso(),
            "offline": bool(offline),
            "messages": serialize_messages(clean),
        }
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(session_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def update_title(self, session_id: str, title: str) -> None:
        """Rewrite only the title (+ updated_at) of an existing session.

        Used by the async titler so a late title write cannot clobber
        messages saved by a turn that finished in the meantime. No-op if the
        session file does not exist (e.g. it was deleted).
        """
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                return
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            data["title"] = title
            data["updated_at"] = _now_iso()
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def load(self, session_id: str) -> dict[str, Any] | None:
        """Return the full session record dict, or None if missing/corrupt."""
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return data if isinstance(data, dict) else None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return per-session metadata, newest-updated first.

        Globs the directory and parses each file; corrupt files are skipped.
        Fine for a personal desktop app's session count.
        """
        with self._lock:
            if not self._dir.exists():
                return []
            paths = sorted(self._dir.glob("*.json"))
        items: list[dict[str, Any]] = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            items.append(
                {
                    "id": data.get("id", path.stem),
                    "title": data.get("title", "未命名会话"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "offline": bool(data.get("offline", False)),
                    "message_count": len(data.get("messages", [])),
                }
            )
        items.sort(key=lambda m: str(m.get("updated_at", "")), reverse=True)
        return items

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if a file was removed."""
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                return False
            path.unlink()
            return True
