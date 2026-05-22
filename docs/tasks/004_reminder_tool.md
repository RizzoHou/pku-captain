# Task 004 — `ReminderTool`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.

## Goal

Implement `ReminderTool` — letting the agent create, list, and delete reminders (e.g. "submit assignment at 10am tomorrow", "see a lecture before Friday"). Part of the core feature #3 tool set.

## Background

The `Tool` abstract base class is in `src/tools/base.py`; reference subclasses are `src/tools/weather.py` (network-backed) and `src/tools/clock.py` (no-parameter). `ToolResult` has fields `success / data / error`.

## Deliverables

- New file `src/tools/reminder.py` — `ReminderTool(Tool)`, plus the reminder persistence store (a small backend class in the same file is fine).
- Edit `src/tools/__init__.py` — export `ReminderTool`.
- Edit `src/core/bootstrap.py` — register `ReminderTool` in `_build_tools()`. Reminders are a purely local operation and offline-safe — **register it in both the online and offline branches** (alongside `ClockTool`, not inside `if not offline:`).
- If you add a new data directory (e.g. `data/`), add it to `.gitignore`.

## Implementation requirements

- A reminder entry has at least: text, trigger time (ISO-8601), creation time, done/not-done status. Persist to a gitignored path inside the repo (e.g. `data/reminders.json`).
- `ReminderTool` dispatches on an `action` parameter — `add` / `list` / `done` / `delete` — with `parameters_schema` clearly describing each action's parameters; time parameters take ISO-8601 strings. `invoke()` returns a `ToolResult`.
- v1 does not require a background timer firing notifications — only storage + querying; actual "fire on time" delivery is a later concern. `list` should support filtering to "future only / not-done only".
- Subclass + register pattern; modules side-effect-free on import; `invoke()` thread-safe (integration contract §5).
- Note the separation from task 003 (memory): memory stores **long-term preferences**, reminders store **time-bound to-dos**. They are independent and each persists separately.

## Dependencies

Independent task.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] `add` a reminder → construct a fresh tool instance → `list` reads it back (verifies persistence).
- [ ] `invoke()` each of `add` / `list` / `done` / `delete` once, with expected results.
- [ ] After `python -m src.cli --offline` starts, `ReminderTool` appears in the tool list.

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
