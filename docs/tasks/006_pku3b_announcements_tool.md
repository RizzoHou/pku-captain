# Task 006 — `PKU3bAnnouncementsTool`

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` (especially the `pku3b` paragraphs) and `docs/integration_contract_zh.md`.

## Goal

Implement `PKU3bAnnouncementsTool` — fetch PKU course-network (Blackboard) announcements / notices via the `pku3b` CLI. Part of the core feature #3 tool set, and a data source for `MorningBriefingWorkflow` (task 007).

## Background

The `pku3b` subprocess wrapper already exists in `src/tools/pku3b.py` (`run_pku3b()`, `strip_ansi()`, `Pku3bNotFoundError` / `Pku3bTimeoutError` — it is **not** a Tool subclass). **Reuse it; do not rewrite the subprocess logic.** The closest reference implementation is `src/tools/pku3b_assignments.py` (`PKU3bAssignmentsTool`) in the same directory — it calls `pku3b assignment list --format json` and `json.loads`es the structured output. This task is its "announcements" counterpart.

`pku3b` is installed at `~/.local/bin/pku3b` (on PATH, usable directly inside a worktree); it is v0.13.0+ from our fork.

## Deliverables

- New file `src/tools/pku3b_announcements.py` — `PKU3bAnnouncementsTool(Tool)`.
- Edit `src/tools/__init__.py` — export `PKU3bAnnouncementsTool`.
- Edit `src/core/bootstrap.py` — register `PKU3bAnnouncementsTool` inside the `if not offline:` branch of `_build_tools()` (subprocess-backed; not in the offline subset).

## Implementation requirements

- **First run `pku3b --help` (and the relevant subcommand's `--help`) to confirm the exact name and parameters of the announcements / notices subcommand.** Prefer `--format json` structured output + `json.loads`; if that subcommand does not yet support JSON, fall back to text output + `strip_ansi()` parsing, and record the limitation under an "Implementation notes" section in this file (the captain decides whether to extend the fork).
- Match `PKU3bAssignmentsTool`'s error handling: catch `Pku3bNotFoundError` / `Pku3bTimeoutError`, turn a non-zero return code into `ToolResult(success=False, error=...)`, and give an actionable message on JSON parse failure.
- One known quirk (noted in `CLAUDE.md`): `pku3b` output fails when redirected to a regular file, but pipes work fine — `subprocess.run(capture_output=True)` uses pipes, so `run_pku3b()` is unaffected; use it as-is.
- `parameters_schema` should be clearly described (optional filters such as by-course are fine); `data` is a structured list of announcements.
- Subclass + register pattern; modules side-effect-free on import; `invoke()` thread-safe (integration contract §5).

## Dependencies

Independent task. Task 007 orchestrates this tool, but this task does not depend on 007.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] Constructing `PKU3bAnnouncementsTool` directly and calling `invoke({})` returns structured announcements (the first call may need a `pku3b` login session — see `docs/setup_zh.md`).
- [ ] When `pku3b` is missing / times out / returns non-zero, `invoke()` returns `ToolResult(success=False, ...)` without raising.
- [ ] `python -m src.cli --offline` still starts (the tool is not registered offline, which is expected).

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
