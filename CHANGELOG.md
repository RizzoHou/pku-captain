# Changelog

All notable changes to PKU Captain are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project is pre-release (no Semantic Versioning yet), so entries are grouped by the date a change landed on `main`, newest first. Deep design rationale and code invariants live in `CLAUDE.md`; this file records *what changed*.

## [Unreleased]

### Changed
- Course-table grid cells now display the full course info inline (上课信息 / 教师 / 考试信息 / 备注), not just the title + note line; the previous info was only reachable via tooltip/click. `_clean_course_info` emits a labelled, newline-joined `detail` and the cell renders it in a new `CourseBlockDetail` label. (worktree `fix-course-note-absence`)
- Thinking-visibility toggle text is now an action label that flips on toggle — `💭 思考可见` when hidden, `💭 思考不可见` when shown (was the misleading static `💭 思考`). (worktree `fix-thinking-visibility-problems`)

### Fixed
- Multi-session course cells (the same course concatenated at different weeks/rooms, e.g. 程序设计实习) no longer leak the next session's text into the previous one's 考试信息. `_clean_course_info` splits on the `<title>(主)` marker via `_split_sessions`, bounds each field to its session, and merges all sessions' 上课信息. (worktree `fix-course-note-absence`)
- `InlineThinking` sliding window now auto-sizes its **height** to the reasoning length (≤160px cap), matching the existing width auto-sizing — short thinking no longer renders in a tall half-empty box. Height is counted from font metrics (`_sync_size_to_text`) since QPlainTextEdit's `documentSize` reads stale right after a width change; a `_saturated` flag keeps streaming O(delta) once both caps are hit. (worktree `fix-thinking-visibility-problems`)

## [2026-06-05]

### Added
- `DeanUpdatesTool` (`src/tools/dean_updates.py`) — proactive Dean's Office dashboard card surfacing public dean.pku.edu.cn list items new since the last check; first run establishes a baseline. (PR #5)
- `TreeholeTool` (`src/tools/treehole_updates.py`) — treehole `search`/`fetch` as an agent tool, no GUI entry by design. (PR #5)
- Startup sync of `pku3b identity --format json` into long-term `MemoryStore` (`bootstrap._sync_pku3b_identity_memory`); runs once and uses `--format json` (not `--raw`) to avoid sensitive portal fields. (PR #5)
- Course-table official notes (`备注`) parsed into `CourseBlock.note` and rendered under the course name in a smaller font. (PR #5)
- Click-to-Safari on dashboard rows / linked sections (`_open_external_url`, falls back to `QDesktopServices`). (PR #5)
- `DeanResourcesTool` (`src/tools/dean_resources.py`) — wraps the `pku-dean-cli` sibling for public dean resources (no login). (worktree `pku-dean-wiring`)
- Optional chain-of-thought ("thinking") visibility — `DeepSeekProvider` streams `reasoning_delta`, rendered in an `InlineThinking` sliding window behind a checkable 💭 思考 toggle (off by default). (worktree `thinking-chunk-visibility`)
- Dashboard card disk cache (`src/core/dashboard_cache.py` `DashboardCache`) for instant paint-from-cache at startup, then a silent refresh that repaints only changed cards. (worktree `downloads-cache`)
- Multi-session chat save/restore + auto-naming — `SessionStore`, `SessionTitler`, and ＋新对话 / 历史会话 GUI controls. (worktree `multi-session`)
- LLM-folded long-term memory: memory merged into each turn's leading system message; keyless `MemoryStore.remember(text)`; dashboard 记忆 box with `MemoryLearnService` LLM fact extraction. (worktree `memory-system`)
- macOS treehole desktop notifications — `TreeholeNotificationService` LaunchAgent + 消息通知 GUI toggle. (worktree `treehole`)
- macOS Calendar DDL notifications — `CalendarReminderTool` writes assignment deadlines into a dedicated Calendar.app calendar with alarms; 加入日历 button on the DDL card. (worktree `ddl-notification`)

### Changed
- Window title trimmed from "PKU Captain 北大信息助手" to "PKU Captain". (PR #5)
- pku3b fork install branch is now `master` (the old `feat/assignment-list-json-output` work merged; `master` also adds `identity --format json`). Re-`cargo install` to pick up `identity`. (PR #5)
- 树洞消息 dashboard card now accumulates unread replies (persisted `TreeholeInboxStore` + `merge_treehole_updates`) and auto-refreshes on the notifier's cadence, instead of replacing on each poll. (worktree `treehole-checking-sync`)

### Fixed
- Restored Python 3.11 compatibility — dropped `from typing import override` (3.12+) from `dashboard.py`. (PR #5 integration)
- Identity startup sync no longer re-auths the portal on every launch — guarded sync-once since `MemoryStore` persists. (PR #5 integration)

## [2026-06-04]

### Removed
- `WeatherTool` and the dashboard weather panel — deleted end to end (kept as a struck-through, justified deferral in `docs/design_reference_zh.md` 核心功能).

### Changed
- Worktree provisioning: `.worktreeinclude` for gitignored paths; worktrees share the main `.venv` via symlink instead of copying (~1.2 GB saved per worktree).

## [2026-06-02]

### Added
- `PLibMaterialsTool` (`src/tools/plib_materials.py`) — wraps the `plib-cli` fork; auto-injects `secrets/plib/{email,password}`. (PR #4)
- `TreeholeUpdatesTool` + `TreeholeAuthService` (`src/tools/treehole_updates.py`) — wraps `pku-treehole-cli`, surfaces login/SMS-verify. (PR #4)
- Dashboard dialogs for treehole / P-Lib / announcements / lectures / reminders / memory / knowledge; GUI collapsed to a 2-panel (dashboard | chat) layout with inline tool calls. (PR #4)

### Changed
- Structured secrets layout (`secrets/api_keys/*`, `secrets/plib/*`, `secrets/treehole/*`); legacy flat paths still read as a fallback. (PR #4)

### Fixed
- Offline tool leak closed — network/subprocess tools register online-only. (PR #4)
- Chat renders one bubble per assistant segment (not per turn), so the final reply renders below its tool calls.
- Dashboard refresh scoped to the requesting card (`partial_refresh_requested`), not a global reload.

## [2026-05-31]

### Changed
- RAG embeddings moved to an API-only path (Alibaba DashScope `text-embedding-v4`); dropped the local BGE/torch stack. RAG is opt-in, off by default (`--rag` / `build_agent(enable_knowledge=...)`). (PR #3)

## [2026-05-26]

### Added
- PyQt6 GUI lane — main window, dashboard, chat sidebar, tool-trace, PKU-red theme; backend `LLMProvider.stream_chat()` + `ChatStreamEvent`, `assistant_delta` agent event, and `PKU3bCourseTableTool`. (PR #2)

## [2026-05-22]

### Added
- Week-2 backend set (merged from parallel worktrees): RAG stack (`Embedder`/`KnowledgeBase`/`KnowledgeSearchTool`), `DeanSource` + `CalendarSource`, `MemoryTool` + `MemoryStore`, `ReminderTool`, `LectureTool`, `PKU3bAnnouncementsTool`, `KimiProvider`, and `MorningBriefingWorkflow`.
- `docs/tasks/` worktree delegation package (guide + 8 task briefs).

### Changed
- `CLAUDE.md` is now tracked in git so `git worktree` sessions inherit project context.

### Fixed
- Broke the `core` ↔ `tools` import cycle via a lazy (PEP 562) `bootstrap` re-export.

## [2026-05-17]

### Added
- `docs/setup_zh.md` (pku3b fork install) and the root `README`.

## [2026-05-16]

### Added
- Week-1 vertical slice: `pku3b` subprocess wrapper + `PKU3bAssignmentsTool` (consumes `assignment list --format json` directly), `DeepSeekProvider` (thinking-mode wire format), and the four offline reference subclasses (`ClockTool`, `EchoLLMProvider`, `StaticSource`, `HelloWorkflow`) on the `Agent` + `Conversation` kernel.
- CLI `/save` command to dump a conversation (including `reasoning_content`) to `debug/`.
