"""KnowledgeBase — SQLite-backed vector store with cosine retrieval.

Stores `Chunk`s (text + metadata) alongside their BGE embedding vectors
in SQLite; vectors are persisted as raw float32 BLOBs. `search` loads
the stored vectors into numpy and ranks them by cosine similarity
against the query embedding.

Chunks are keyed by `(source_name, identifier)`; re-indexing the same
key overwrites the previous row, so `index` is idempotent. SHA-256
incremental diffing (skip-if-unchanged) is a later-window concern — this
class only needs "can index, can search".
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

import numpy as np

from .embedder import APIEmbedder, Embedder
from .source import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    source_name TEXT NOT NULL,
    identifier  TEXT NOT NULL,
    text        TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    vector      BLOB NOT NULL,
    dimension   INTEGER NOT NULL,
    PRIMARY KEY (source_name, identifier)
);
"""


class KnowledgeBase:
    """A persistent, searchable store of embedded knowledge chunks."""

    def __init__(
        self,
        db_path: str = ":memory:",
        embedder: Embedder | None = None,
    ) -> None:
        self.embedder = embedder if embedder is not None else APIEmbedder()
        # check_same_thread=False so a KB built on one thread can be queried
        # from the GUI's AgentWorker thread (see integration_contract_zh.md).
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def index(self, chunks: Iterable[Chunk]) -> int:
        """Embed and store `chunks`. Returns the number indexed.

        Existing rows with the same `(source_name, identifier)` are
        replaced, so calling this repeatedly is safe.
        """
        items = list(chunks)
        if not items:
            return 0
        vectors = self.embedder.encode([c.text for c in items])
        rows = [
            (
                c.source_name,
                c.identifier,
                c.text,
                json.dumps(c.metadata, ensure_ascii=False),
                vec.astype(np.float32).tobytes(),
                int(vec.shape[0]),
            )
            for c, vec in zip(items, vectors, strict=True)
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunks "
            "(source_name, identifier, text, metadata, vector, dimension) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        """Number of chunks currently stored."""
        return int(self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return the `top_k` chunks most similar to `query`.

        Each result is a JSON-serializable dict: `text`, `source`,
        `identifier`, `metadata`, and `score` (cosine similarity in
        `[-1, 1]`, as a plain `float`). Results are sorted by descending
        score; an empty store yields an empty list.
        """
        rows = self._conn.execute(
            "SELECT source_name, identifier, text, metadata, vector FROM chunks"
        ).fetchall()
        if not rows or top_k <= 0:
            return []

        matrix = np.vstack(
            [np.frombuffer(r[4], dtype=np.float32) for r in rows]
        )
        query_vec = self.embedder.encode([query])[0]
        # Vectors are L2-normalized at encode time, so the dot product is
        # the cosine similarity directly.
        scores = matrix @ query_vec

        order = np.argsort(scores)[::-1][:top_k]
        return [
            {
                "text": rows[i][2],
                "source": rows[i][0],
                "identifier": rows[i][1],
                "metadata": json.loads(rows[i][3]),
                "score": float(scores[i]),
            }
            for i in order
        ]

    def close(self) -> None:
        self._conn.close()
