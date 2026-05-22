"""BGEEmbedder — encode Chinese text into dense vectors.

Wraps `BAAI/bge-large-zh-v1.5` (a SentenceTransformer model). The model
weights are large and slow to load, so they are loaded lazily on the
first `encode()` call — never at module import or object construction.
This keeps offline GUI development (which never registers the
knowledge-search tool) free of the embedding dependency.

`bge-large-zh-v1.5` does not need a retrieval instruction prefix on
queries (that was a v1.0-era requirement), so `encode` treats query and
passage text identically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # avoid importing the heavy dependency at module load
    from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "BAAI/bge-large-zh-v1.5"


class BGEEmbedder:
    """Lazy-loading wrapper around a BGE SentenceTransformer model."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: SentenceTransformer | None = None

    def _ensure_loaded(self) -> SentenceTransformer:
        if self._model is None:
            # Imported here, not at module scope: the import alone pulls in
            # torch + transformers, which offline development must not pay.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        """Embedding dimension of the loaded model (loads the model)."""
        model = self._ensure_loaded()
        # `get_sentence_embedding_dimension` was renamed in newer
        # sentence-transformers releases; support both.
        getter = getattr(
            model,
            "get_embedding_dimension",
            model.get_sentence_embedding_dimension,
        )
        return int(getter())

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode `texts` into an L2-normalized float32 matrix.

        Returns shape `(len(texts), dimension)`. Normalization means a
        plain dot product between two rows equals their cosine similarity.
        """
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        model = self._ensure_loaded()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)
