"""Embedder hierarchy — encode text into dense vectors for retrieval.

The RAG knowledge base ranks chunks by cosine similarity, so every
`Embedder` must return an **L2-normalized float32** matrix: with unit
rows, a plain dot product equals the cosine similarity, which is what
`KnowledgeBase.search` relies on.

The project embeds via a hosted API rather than a local model — there is
no multi-gigabyte download and no torch/transformers dependency, and the
hosted model can be swapped for a stronger one without touching the app.
`APIEmbedder` targets Alibaba DashScope's `text-embedding-v4` through its
OpenAI-compatible endpoint, hit with `requests` directly (mirroring
`DeepSeekProvider` / `KimiProvider`, no `openai` SDK).
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import numpy as np
import requests

DEFAULT_MODEL = "text-embedding-v4"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# DashScope caps the number of inputs per embeddings request; stay well
# under it. The curated corpus is tiny, so this only ever matters as a
# safety net against a future large source.
DEFAULT_BATCH_SIZE = 10


class EmbeddingAPIError(RuntimeError):
    """Raised when the embedding API returns a non-2xx response."""


class Embedder(ABC):
    """Abstract text embedder.

    `encode` returns an L2-normalized float32 matrix of shape
    `(len(texts), dimension)`; an empty input yields an empty array.
    """

    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode `texts` into an L2-normalized float32 matrix."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimension produced by this embedder."""


class APIEmbedder(Embedder):
    """Embed text via DashScope's OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        dimensions: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: float = 60.0,
    ) -> None:
        api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise ValueError(
                "api_key is required (pass it explicitly or set DASHSCOPE_API_KEY)"
            )
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self._probed_dim: int | None = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return _l2_normalize(np.asarray(vectors, dtype=np.float32))

    @property
    def dimension(self) -> int:
        if self.dimensions is not None:
            return int(self.dimensions)
        if self._probed_dim is None:
            self._probed_dim = int(self.encode(["维度探测"]).shape[1])
        return self._probed_dim

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        body: dict[str, object] = {"model": self.model, "input": batch}
        if self.dimensions is not None:
            body["dimensions"] = self.dimensions
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise EmbeddingAPIError(
                f"embeddings API {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        # OpenAI-compatible shape: data["data"] is a list of {index, embedding}.
        items = sorted(data["data"], key=lambda d: d.get("index", 0))
        return [item["embedding"] for item in items]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length so dot product == cosine similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # leave all-zero rows untouched (avoid div-by-zero)
    return (matrix / norms).astype(np.float32)
