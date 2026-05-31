"""Unit tests for APIEmbedder — fully mocked, no network."""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.rag.embedder import APIEmbedder, EmbeddingAPIError


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        APIEmbedder(api_key=None)


def test_encode_empty_returns_empty() -> None:
    out = APIEmbedder(api_key="sk-test").encode([])
    assert out.shape == (0, 0)
    assert out.dtype == np.float32


def test_encode_batches_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_sizes: list[int] = []

    def fake_post(url, headers=None, data=None, timeout=None):
        batch = json.loads(data)["input"]
        batch_sizes.append(len(batch))
        # length-4 vectors with non-unit norm, so normalization is observable
        items = [
            {"index": i, "embedding": [float(len(t)), 2.0, 0.0, 0.0]}
            for i, t in enumerate(batch)
        ]
        return _FakeResponse(200, {"data": items})

    monkeypatch.setattr("src.rag.embedder.requests.post", fake_post)

    out = APIEmbedder(api_key="sk-test", batch_size=2).encode(["a", "bb", "ccc", "d", "e"])

    assert out.shape == (5, 4)
    assert out.dtype == np.float32
    assert batch_sizes == [2, 2, 1]  # chunked at batch_size=2
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-6)


def test_encode_orders_by_response_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url, headers=None, data=None, timeout=None):
        batch = json.loads(data)["input"]
        n = len(batch)
        # one-hot per input, returned in REVERSED order to exercise the sort
        items = [{"index": i, "embedding": [1.0 if j == i else 0.0 for j in range(n)]}
                 for i in range(n)]
        return _FakeResponse(200, {"data": list(reversed(items))})

    monkeypatch.setattr("src.rag.embedder.requests.post", fake_post)

    out = APIEmbedder(api_key="sk-test", batch_size=10).encode(["x", "y", "z"])
    assert np.allclose(out, np.eye(3, dtype=np.float32), atol=1e-6)


def test_non_2xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.rag.embedder.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": "invalid key"}),
    )
    with pytest.raises(EmbeddingAPIError):
        APIEmbedder(api_key="sk-test").encode(["x"])
