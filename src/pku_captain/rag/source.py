"""Source abstract base class and registry.

A Source is a knowledge feed (DeanSource, CalendarSource, ...) that the
RAG pipeline polls on its own `refresh_interval`. Subclasses implement
`fetch` returning raw chunks; the pipeline owns hashing, embedding, and
storage downstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class Chunk:
    """A unit of fetched content destined for the knowledge base."""

    source_name: str
    identifier: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Source(ABC):
    """Abstract polling source for the RAG pipeline."""

    name: ClassVar[str]
    refresh_interval: ClassVar[int]  # seconds

    @abstractmethod
    def fetch(self) -> Iterable[Chunk]:
        """Fetch the current state of this source as a sequence of chunks."""


@dataclass
class SourceRegistry:
    _sources: dict[str, Source] = field(default_factory=dict)

    def register(self, source: Source) -> None:
        if source.name in self._sources:
            raise ValueError(f"source already registered: {source.name}")
        self._sources[source.name] = source

    def get(self, name: str) -> Source:
        return self._sources[name]

    def all(self) -> list[Source]:
        return list(self._sources.values())
