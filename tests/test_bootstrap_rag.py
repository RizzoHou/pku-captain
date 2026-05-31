"""RAG is opt-in: knowledge_search registers only when enabled AND online."""

from __future__ import annotations

import numpy as np
import pytest

from src.core import bootstrap
from src.rag import Embedder, KnowledgeBase


class _FakeEmbedder(Embedder):
    def encode(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 2), dtype=np.float32)

    @property
    def dimension(self) -> int:
        return 2


def _names(offline: bool, enable_knowledge: bool) -> set[str]:
    reg = bootstrap._build_tools(offline=offline, enable_knowledge=enable_knowledge)
    return {tool.name for tool in reg.all()}


def test_knowledge_off_by_default() -> None:
    names = _names(offline=False, enable_knowledge=False)
    assert "knowledge_search" not in names
    assert "weather" in names  # other online tools still register


def test_knowledge_never_registers_offline() -> None:
    assert "knowledge_search" not in _names(offline=True, enable_knowledge=True)


def test_knowledge_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub the KB builder so the opt-in path needs neither key nor network.
    monkeypatch.setattr(
        bootstrap,
        "_build_knowledge_base",
        lambda: KnowledgeBase(embedder=_FakeEmbedder()),
    )
    assert "knowledge_search" in _names(offline=False, enable_knowledge=True)
