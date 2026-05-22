# Task 001 — `DeanSource` + `CalendarSource` (Source subclasses)

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md` §5.

## Goal

Implement two `Source` subclasses so the RAG knowledge base and the dashboard can pull data from PKU's official information sources:

- `DeanSource` — PKU Dean's Office (教务部) notices / announcements.
- `CalendarSource` — PKU academic calendar (term weeks, holidays, exam weeks, etc.).

## Background

The `Source` abstract base class and `SourceRegistry` already exist in `src/rag/source.py`; the offline reference subclass `StaticSource` is in `src/rag/static.py`. `Source.fetch()` returns `Iterable[Chunk]`, where `Chunk` has fields `source_name / identifier / text / metadata`. The RAG pipeline owns downstream hashing, embedding, and storage — a Source only fetches and splits content into chunks.

## Deliverables

- New file `src/rag/dean.py` — `DeanSource(Source)`.
- New file `src/rag/calendar.py` — `CalendarSource(Source)`.
- Edit `src/rag/__init__.py` — export `DeanSource`, `CalendarSource`.
- Edit `src/core/bootstrap.py` — add a factory function `build_source_registry() -> SourceRegistry` that `register()`s both Sources. The dashboard (GUI lane) will obtain its `SourceRegistry` through this factory (see integration contract §5).

## Implementation requirements

- Subclass `Source`, set `name` and `refresh_interval` (seconds; ~1h for Dean notices, ~24h for the calendar), and implement `fetch()`.
- `fetch()` splits fetched content into reasonably-sized `Chunk`s: `identifier` must be stable and unique within the source (so downstream SHA diffing works); put title, URL, publish date, etc. in `metadata`.
- On a network failure, raise or return empty — do not silently swallow the error into a `Chunk`.
- Subclass + register pattern; modules must be side-effect-free on import — registration happens only at the `build_source_registry()` call site.
- If a source has no stable public data interface, implement it to read a fixed data file checked into the repo (keep the `fetch()` shape unchanged), and record this under an "Implementation notes" section in this file — the captain wires the real source later.

## Dependencies

Independent task. Do not depend on task 002 — 002 self-tests with `StaticSource`.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] `DeanSource()` / `CalendarSource()` can be constructed and `fetch()` returns a non-empty `Chunk` sequence (or the fixed-file fallback above when the data source is unavailable).
- [ ] `build_source_registry().all()` returns both Sources.
- [ ] `python -m src.cli --offline` still starts.

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing, so nothing is lost when the worktree is cleaned up.
