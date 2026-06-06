"""SessionTitler — auto-name a chat session from its opening exchange.

Uses a lightweight model (`deepseek-v4-flash` in non-think mode, wired in
`bootstrap.build_session_titler`) for a cheap, fast one-shot title. The call
is deliberately standalone: it sends a single synthetic user prompt built
from the conversation's first exchange, NOT the real message history — so
there are no tool-call / `reasoning_content` replay concerns.

Degrades gracefully: if no provider is supplied (offline), or the call
raises or returns nothing usable, it falls back to a heuristic title (the
first user message, truncated). The offline path passes `provider=None`
rather than `EchoLLMProvider`, so a title is never `"echo: ..."`.
"""

from __future__ import annotations

from ..llm.base import ChatMessage, LLMProvider

_MAX_TITLE_LEN = 18
_PROMPT_CONTEXT_LEN = 200

_PROMPT_TEMPLATE = (
    "为下面这段对话起一个简短的中文标题，用于会话列表。要求：不超过12个字，"
    "概括主题，只输出标题本身，不要加引号、标点或任何解释。\n\n"
    "用户：{user}\n助手：{assistant}"
)

# Quote-like characters the model sometimes wraps the title in.
_STRIP_CHARS = " \t\r\n\"'`“”‘’「」『』《》【】*#"


class SessionTitler:
    """Generate a short session title, with a heuristic offline fallback."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self._provider = provider

    def generate(self, messages: list[ChatMessage]) -> str:
        """Return a short title for the conversation.

        Never raises: any provider error or empty result falls back to the
        heuristic. May make one network call (the flash model), so callers
        run it off the GUI thread.
        """
        first_user = _first_content(messages, "user")
        if not first_user or self._provider is None:
            return self.heuristic(messages)

        first_assistant = _first_content(messages, "assistant")
        prompt = _PROMPT_TEMPLATE.format(
            user=first_user[:_PROMPT_CONTEXT_LEN],
            assistant=(first_assistant or "（暂无回复）")[:_PROMPT_CONTEXT_LEN],
        )
        try:
            response = self._provider.chat([ChatMessage(role="user", content=prompt)])
        except Exception:  # noqa: BLE001 - titling must never break a turn
            return self.heuristic(messages)

        return _clean_title(response.text) or self.heuristic(messages)

    def heuristic(self, messages: list[ChatMessage]) -> str:
        """Network-free title (first user message, truncated).

        Used for the provisional title written synchronously on the GUI
        thread before the async `generate` upgrade arrives, and as the
        fallback inside `generate`. Returns "新会话" if there is no user
        message yet.
        """
        first_user = _first_content(messages, "user")
        return _heuristic(first_user) if first_user else "新会话"


def _first_content(messages: list[ChatMessage], role: str) -> str:
    for msg in messages:
        # Skip multimodal messages (doc_read page images, content is a list):
        # the title comes from the user's typed text, which is a plain string.
        if msg.role == role and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""


def _clean_title(text: str) -> str:
    """Take the first non-empty line, strip wrapping quotes, truncate."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = line.strip(_STRIP_CHARS)
    if line.startswith("标题：") or line.startswith("标题:"):
        line = line.split("：", 1)[-1].split(":", 1)[-1].strip(_STRIP_CHARS)
    return _truncate(line)


def _heuristic(first_user: str) -> str:
    """Fallback title: the first user message, condensed and truncated."""
    line = next((ln.strip() for ln in first_user.splitlines() if ln.strip()), first_user)
    return _truncate(line.strip()) or "新会话"


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TITLE_LEN:
        return text
    return text[:_MAX_TITLE_LEN] + "…"
