# Task 002 — RAG stack: BGE embedder + `KnowledgeBase` + `KnowledgeSearchTool`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.

## Goal

Implement the full knowledge-base retrieval chain, exposed as a tool the agent can call:

1. **BGE embedder** — encode Chinese text into vectors with `BAAI/bge-large-zh-v1.5`.
2. **`KnowledgeBase`** — store chunks + vectors in SQLite, do cosine similarity retrieval with numpy.
3. **`KnowledgeSearchTool`** — a `Tool` subclass exposing retrieval to the LLM.

Complete all three serially in this order; together they are one independent task.

## Background

The `Tool` abstract base class is in `src/tools/base.py`; a reference subclass is `src/tools/weather.py`. `Source` / `Chunk` are in `src/rag/source.py`; the offline reference source `StaticSource` is in `src/rag/static.py`. The stack is fixed: SQLite + numpy for vectors, BGE-large-zh for embeddings.

## Deliverables

- New file `src/rag/embedder.py` — the BGE embedder (a small class, e.g. `encode(texts) -> np.ndarray`).
- New file `src/rag/knowledge_base.py` — `KnowledgeBase`: schema creation, `index(chunks)`, `search(query, top_k) -> list[result]`.
- New file `src/tools/knowledge_search.py` — `KnowledgeSearchTool(Tool)`.
- Edit `src/rag/__init__.py` and `src/tools/__init__.py` — export the new symbols.
- Edit `src/core/bootstrap.py` — register `KnowledgeSearchTool` inside the `if not offline:` branch of `_build_tools()` (the embedding model is slow to load; offline GUI development should not trigger it, so register online only).
- Edit `pyproject.toml` — add the embedding dependency (e.g. `sentence-transformers`, or `transformers` + `torch`) to `dependencies`.

## Implementation requirements

- **Lazy-load the embedding model**: load weights on the first `encode()` call, not at module import or object construction (first-load latency / memory footprint is a registered project risk).
- `KnowledgeBase` persists chunk text, metadata, and vectors in SQLite (vectors can be stored as BLOBs); on retrieval, load into numpy for cosine similarity. SHA-256 incremental diffing is a final-window concern — this task only needs "can index, can search".
- `KnowledgeSearchTool`: `parameters_schema` takes a required `query` and an optional `top_k`; `invoke()` returns a `ToolResult` whose `data` is the list of hit chunks (with text, source, similarity score).
- Subclass + register pattern; modules side-effect-free on import.
- **Self-test with `StaticSource`; do not depend on task 001.** In bootstrap, the `KnowledgeBase` behind `KnowledgeSearchTool` may be built from a small set of built-in sample chunks (or `StaticSource`); the captain wires in `DeanSource` / `CalendarSource` during integration.

## Dependencies

Independent task.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] A library can be built from sample `Chunk`s, and `KnowledgeBase.search()` returns reasonably-ranked results for a relevant query.
- [ ] Constructing `KnowledgeSearchTool` directly and calling `invoke({"query": ...})` returns `success=True`.
- [ ] `python -m src.cli --offline` still starts (the tool is not registered offline, which is expected).

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
