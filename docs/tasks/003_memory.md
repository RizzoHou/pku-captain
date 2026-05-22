# Task 003 — Memory backend + `MemoryTool`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.

## Goal

Implement core feature #6, "persistent personal-preference memory":

- **Memory backend** — a preference store that persists across sessions.
- **`MemoryTool`** — a `Tool` subclass letting the agent read and write memory.

## Background

The `Tool` abstract base class is in `src/tools/base.py`; a reference subclass is `src/tools/weather.py`. Memory here means **user preferences** (e.g. "I live in Yan'an Garden", "I have class at 8am daily", "remind me in Chinese") — not conversation history, which `Conversation` already handles.

## Deliverables

- New file `src/core/memory.py` — the memory backend: create / read / update / delete preference entries, persisted to a local file. (Memory is user preferences, not RAG-retrieved content, so it belongs in `src/core`, not `src/rag`.)
- New file `src/tools/memory.py` — `MemoryTool(Tool)`.
- Edit `src/tools/__init__.py` — export `MemoryTool`.
- Edit `src/core/bootstrap.py` — register `MemoryTool` in `_build_tools()`. Memory is a purely local operation and offline-safe — **register it in both the online and offline branches** (alongside `ClockTool`, not inside `if not offline:`).
- If you add a new data directory (e.g. `data/`), add it to `.gitignore`.

## Implementation requirements

- Persist with SQLite or JSON, either is fine; place the file in a gitignored directory inside the repo (e.g. `data/memory.json`). Entries should be structured: key, value, write timestamp.
- `MemoryTool` dispatches on an `action` parameter — `set` / `get` / `list` / `delete` — with `parameters_schema` clearly describing each action's parameters; `invoke()` returns a `ToolResult`.
- Keep backend and tool separate: the backend class must not depend on `Tool`, so workflows and the dashboard can reuse it directly.
- Subclass + register pattern; modules side-effect-free on import. Thread-safety: `invoke()` must not share mutable state (integration contract §5 requires Tools to be thread-safe).
- "Folding memory into responses" is a Week 3 task — this task only delivers the backend + tool.

## Dependencies

Independent task.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] Write a preference → construct a fresh backend instance → read it back (verifies persistence).
- [ ] Construct `MemoryTool` directly and `invoke()` each of `set` / `get` / `list` / `delete` once, with expected results.
- [ ] After `python -m src.cli --offline` starts, `MemoryTool` appears in the tool list.

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
