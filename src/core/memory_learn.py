"""MemoryLearnService — turn a free-text sentence into clean stored facts.

The dashboard 记忆 box and the chat agent both want "user typed a
description → remember it". The agent does this inline via its tool loop;
this service is the dashboard's equivalent. It asks an `LLMProvider` to
split the note into atomic durable facts and stores each through
`MemoryStore.remember`. If the model is unavailable, returns nothing
parseable, or finds no facts, it falls back to storing the text verbatim —
so the user's 记住 click always persists *something*, online or offline
(offline `EchoLLMProvider` never yields JSON, so it degrades to verbatim).

This is a dedicated stateless extraction, not a detour through
`Agent.turn()`: same user-visible result, but no chat-history pollution
and no event noise. It lives outside `memory.py` so `MemoryStore` stays a
pure storage class with no LLM dependency.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..llm.base import ChatMessage, LLMProvider
from .memory import MemoryStore

_EXTRACTION_SYSTEM = (
    "You extract durable facts about the user from a short note they want "
    "remembered. Return ONLY a JSON array of strings, each a single atomic "
    'fact in the user\'s own language (e.g. ["住在燕园", "喜欢用中文交流"]). '
    "Split a compound sentence into separate facts. Omit transient or "
    "one-off details. If there is nothing worth remembering, return []."
)


@dataclass(frozen=True)
class MemoryLearnResult:
    """Outcome of a `learn` call."""

    stored: list[str]
    extracted: bool  # True: LLM split into facts. False: verbatim fallback.


class MemoryLearnService:
    """LLM-backed extraction over a shared `MemoryStore`."""

    def __init__(self, llm: LLMProvider, store: MemoryStore) -> None:
        self._llm = llm
        self._store = store

    def learn(self, text: str) -> MemoryLearnResult:
        text = text.strip()
        if not text:
            raise ValueError("memory text must be a non-empty string")
        facts = self._extract(text)
        if facts:
            for fact in facts:
                self._store.remember(fact)
            return MemoryLearnResult(stored=facts, extracted=True)
        # No facts extracted (model unavailable / unparseable / genuinely
        # nothing). The user clicked 记住, so persist the raw text verbatim.
        self._store.remember(text)
        return MemoryLearnResult(stored=[text], extracted=False)

    def _extract(self, text: str) -> list[str]:
        try:
            response = self._llm.chat(
                [
                    ChatMessage(role="system", content=_EXTRACTION_SYSTEM),
                    ChatMessage(role="user", content=text),
                ]
            )
        except Exception:  # noqa: BLE001 — any LLM/network failure → verbatim
            return []
        return _parse_facts(response.text)


def _parse_facts(text: str) -> list[str]:
    """Best-effort parse of a JSON string-array from an LLM reply.

    Tolerates ```code fences``` and surrounding prose by extracting the
    first/last-bracketed array. Returns only non-empty string items; any
    other shape yields [] (→ caller falls back to verbatim). The parser is
    the feature: too strict here and every real reply silently degrades to
    a single verbatim blob.
    """
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
