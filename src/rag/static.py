"""StaticSource — reference Source subclass.

Yields a fixed list of chunks supplied at construction time. Useful for
exercising the RAG pipeline (hashing, embedding, KnowledgeSearchTool)
without hitting the network. Real Week-2 sources (DeanSource,
CalendarSource) follow the same shape with real fetchers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from .source import Chunk, Source


class StaticSource(Source):
    name: ClassVar[str] = "static"
    refresh_interval: ClassVar[int] = 24 * 3600

    def __init__(self, chunks: Iterable[Chunk]) -> None:
        self._chunks = list(chunks)

    def fetch(self) -> Iterable[Chunk]:
        return list(self._chunks)
