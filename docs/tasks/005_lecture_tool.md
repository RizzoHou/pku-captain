# Task 005 — `LectureTool`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.

## Goal

Implement `LectureTool` — letting the agent query recent PKU lecture information (title, time, location, speaker). Part of the core feature #3 tool set, and a data source for `MorningBriefingWorkflow` (task 007).

## Background

The `Tool` abstract base class is in `src/tools/base.py`; the network-backed reference subclass is `src/tools/weather.py` (`requests`, timeout, `requests.RequestException` caught and turned into `ToolResult(success=False, ...)`).

## Deliverables

- New file `src/tools/lecture.py` — `LectureTool(Tool)`.
- Edit `src/tools/__init__.py` — export `LectureTool`.
- Edit `src/core/bootstrap.py` — register `LectureTool` inside the `if not offline:` branch of `_build_tools()` (network-backed tool; not in the offline subset).

## Implementation requirements

- `parameters_schema` may take optional filter parameters (e.g. `limit`, date range / keyword); `invoke()` returns a `ToolResult` whose `data` is a list of lectures, each with title, time, location, speaker, link.
- Network errors, timeouts, and empty results must all be handled into `ToolResult(success=False, error=...)` or `success=True` + empty list — do not let exceptions propagate (see `WeatherTool`'s `try/except`).
- Research the public source for PKU lecture information yourself. **If no stable public interface is available**: implement the tool to read a fixed JSON file checked into the repo (keep the `Tool` interface and `parameters_schema` unchanged), and record the data source used and its limitations under an "Implementation notes" section in this file — the captain wires the real source later. Feature completeness takes priority over data freshness.
- Subclass + register pattern; modules side-effect-free on import; `invoke()` thread-safe (integration contract §5).

## Dependencies

Independent task. Task 007 orchestrates this tool, but this task does not depend on 007.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] Constructing `LectureTool` directly and calling `invoke({})` returns a structured lecture list (or the fallback above).
- [ ] When offline / the data source is unavailable, `invoke()` returns a `ToolResult` (no exception).
- [ ] `python -m src.cli --offline` still starts (the tool is not registered offline, which is expected).

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
