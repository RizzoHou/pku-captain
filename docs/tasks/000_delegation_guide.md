# Week 2 Backend Task Delegation Guide

The `001`–`008` files in this directory are self-contained task briefs, each meant to be delegated to one **worktree Claude**. This file explains how to delegate and integrate them. Audience: the captain (`RizzoHou`), not the worktree Claudes.

## Task list and dependencies

| # | Task | Depends on | Optional |
| --- | --- | --- | --- |
| 001 | `DeanSource` + `CalendarSource` (Source subclasses) | none | |
| 002 | RAG stack: BGE embedder + `KnowledgeBase` + `KnowledgeSearchTool` | none | |
| 003 | Memory backend + `MemoryTool` | none | |
| 004 | `ReminderTool` | none | |
| 005 | `LectureTool` | none | |
| 006 | `PKU3bAnnouncementsTool` | none | |
| 007 | `MorningBriefingWorkflow` | **005, 006** (orchestrates their tools); 001 recommended | |
| 008 | `KimiProvider` (vision LLM) | none | optional — cut-list item #1 |

**Two waves:**

- **Wave A (001–006, 008)** — no inter-task dependencies; delegate all in parallel.
- **Wave B (007)** — orchestrates the tools from 005/006, so delegate it only after Wave A is merged into `main`. Otherwise the workflow it produces references tools that don't exist in its worktree and can't be self-tested end-to-end.

002 is internally an embedder → KnowledgeBase → KnowledgeSearchTool chain, but a single worktree Claude completes it serially — it is one independent task with no cross-worktree dependency.

## How to delegate

Parallel or sequential — both work. The only hard constraint is that **merges must be sequential** (see below); the worktrees themselves can run in parallel.

Each task gets its own worktree with an explicit name. Run from the repo root.

### Full command list

**Wave A** — independent; run any or all in parallel, each in its own terminal:

```bash
cd /home/ubuntu/projects/pku-captain

claude --worktree worktree-001-sources "Read and fully implement docs/tasks/001_source_subclasses.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-002-rag-stack "Read and fully implement docs/tasks/002_rag_stack.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-003-memory "Read and fully implement docs/tasks/003_memory.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-004-reminder "Read and fully implement docs/tasks/004_reminder_tool.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-005-lecture "Read and fully implement docs/tasks/005_lecture_tool.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-006-announcements "Read and fully implement docs/tasks/006_pku3b_announcements_tool.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."

claude --worktree worktree-008-kimi "Read and fully implement docs/tasks/008_kimi_provider.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."
```

**Wave B** — run only after Wave A is merged into `main`:

```bash
cd /home/ubuntu/projects/pku-captain

claude --worktree worktree-007-morning-briefing "Read and fully implement docs/tasks/007_morning_briefing_workflow.md. Work through the acceptance checklist at the end of the file. Commit to the current worktree branch using Conventional Commits. Do not push, do not merge."
```

For sequential delegation, run one command at a time and merge its branch before starting the next.

Notes:

- **The `--worktree` name is mandatory.** Its name argument is optional to the flag, so `claude --worktree "Read ..."` swallows the prompt as the worktree name. Always pass name and prompt as two separate arguments.
- A `worktree-` prefixed name lets the worktree Claude confirm it is "in a worktree" and follow the commit-only / no-push rule.
- Task files are already on `main`, so every worktree reads them directly — no manual copying.
- Each worktree Claude builds its own `.venv` and installs dependencies (`.venv/` and `secrets/` are gitignored and not copied into a worktree). A worktree can therefore only run **offline checks** (`python -m src.cli --offline`, `py_compile`, `ruff`); the online agent needs a DeepSeek key and won't run. The task briefs are written around this.
- **Dry-run one before fanning out.** For the first delegation, run task 004 alone (smallest, fully independent, no network). Confirm the worktree Claude reads its brief, self-checks against the acceptance list, and stops at the commit-only / no-push boundary. Then fan out the rest.

## Integration (merge)

A worktree Claude commits only to its own branch — it does not push or merge (the worktree rule). Integration is the captain's job.

**Merge in numeric order (001 → 008).** 007 lands after 005/006, which numeric order already satisfies.

```bash
cd /home/ubuntu/projects/pku-captain
git worktree list            # show each worktree path and branch name
git checkout main

git merge worktree-001-sources
find src -name '*.py' -print0 | xargs -0 python -m py_compile   # verify after each merge
git merge worktree-002-rag-stack
find src -name '*.py' -print0 | xargs -0 python -m py_compile
# ... merge 003–008 in turn (branch names per `git worktree list` output)
```

### Shared-file conflicts

Worktree Claudes touch these shared files to register their work:

- `src/core/bootstrap.py` — registers new Tool / Workflow / Source.
- `src/{tools,rag,workflows,llm}/__init__.py` — exports new symbols.
- `pyproject.toml` — only 002 adds embedding dependencies.

Parallel merges will conflict on these. The conflicts are **purely additive** (each side adds new lines; no line's meaning is changed), so the resolution is always the same: **keep the new lines from both sides**. Merging in numeric order lets git auto-resolve most of them.

Worktree Claudes do **not** edit `docs/roadmap_zh.md` — the roadmap is captain-maintained. After all merges, the captain ticks the checkboxes and appends the involver handle.

## Wrap-up

After all branches are merged:

```bash
find src -name '*.py' -print0 | xargs -0 python -m py_compile
ruff check src
python -m src.cli --offline          # offline REPL should start
python -m src.cli                    # online (needs secrets/deepseek_key.txt)
python scripts/smoke_deepseek.py     # end-to-end probe
```

Tick the completed Week 2 items in `docs/roadmap_zh.md` and append `— @RizzoHou`, then `git push` (main is pre-authorized). Clean up worktrees:

```bash
git worktree remove <worktree-path>   # for each worktree
```
