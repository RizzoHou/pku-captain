# Task 007 — `MorningBriefingWorkflow`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.
>
> **Wave B task**: this orchestrates the tools produced by task 005 (`LectureTool`) and 006 (`PKU3bAnnouncementsTool`). Before delegating this task, 005 and 006 (and ideally 001) should already be merged into `main` — otherwise those tools do not exist in this worktree and the workflow cannot be self-tested end-to-end.

## Goal

Fully implement `MorningBriefingWorkflow` — compose the results of multiple tools into a "morning briefing": today's DDLs, course announcements, recent lectures, weather. Part of core feature #4, multi-step workflows.

## Background

The `Workflow` abstract base class is in `src/workflows/base.py`: it takes a `ToolRegistry` at construction (stored as `self.tools`) and implements `run()` returning a `WorkflowResult` (`success / summary / details / error`). The reference subclass `src/workflows/hello.py` (`HelloWorkflow`) shows the simplest "call one tool → wrap the result" shape. This task extends that into multi-tool orchestration.

Available tools (fetch by `name` from `self.tools`):

- `pku3b_assignments` — assignments / DDLs (already exists).
- `weather` — weather (already exists).
- `pku3b_announcements` — course announcements (task 006).
- `lecture` — lectures (task 005).
- `clock` — current time (already exists).

## Deliverables

- New file `src/workflows/morning_briefing.py` — `MorningBriefingWorkflow(Workflow)`.
- Edit `src/workflows/__init__.py` — export `MorningBriefingWorkflow`.
- Edit `src/core/bootstrap.py` — register `MorningBriefingWorkflow` in `_build_workflows()`.

## Implementation requirements

- `run()` calls the tools above via `invoke()` in turn and aggregates results into a `WorkflowResult`: `summary` is a human-readable briefing, `details` stores the raw results keyed by tool name.
- **Graceful degradation**: before fetching a tool from `self.tools`, check whether it is registered (in `offline` mode `weather` / `pku3b_*` / `lecture` are all absent). If a tool is missing or its `invoke()` returns `success=False`, skip that section and note it in the briefing — **do not** fail the whole workflow. Return `success=False` only when no data source at all is reachable.
- `ToolRegistry` exposes `get(name)` (raises `KeyError` on a miss), `all()`, and `register()`. Check existence with something like `any(t.name == "lecture" for t in self.tools.all())`.
- Subclass + register pattern; modules side-effect-free on import.
- For time-awareness, use the `clock` tool to get the current date, then filter "today's" DDLs and "recent" lectures.

## Dependencies

Depends on tasks 005 and 006 being merged (task 001 ideally merged too). 002 / 003 / 004 are unrelated to this task.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] Constructing the workflow with a `ToolRegistry` that has all tools registered, `run()` returns `success=True` and `summary` includes every section.
- [ ] Constructing it with a `ToolRegistry` that has **only some tools** registered, `run()` still returns gracefully — missing sections are noted, no exception raised.
- [ ] `python -m src.cli --offline` still starts.

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
