# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo status

Scaffolded but not yet running end-to-end. `src/` is the Python package (importable as `src`; modules use intra-package relative imports so the name `src` rarely shows up in code) and houses the four OOP hierarchies in subpackages — `tools/`, `workflows/`, `llm/`, `rag/`, plus `core/` (agent kernel — `Agent` + `Conversation`) and `ui/` (PyQt6 shell). `pyproject.toml` declares the build (hatchling, `packages = ["src"]`) + runtime deps (PyQt6, requests, numpy, sentence-transformers) + dev deps (pytest, ruff, mypy). No pytest suite yet, but `scripts/smoke_deepseek.py` is a real end-to-end probe of the agent loop against the DeepSeek API — run it after any change to `core/`, `llm/`, or the tool-call wire format. `src/cli.py` (`python -m src.cli`, flags `--offline` / `--show-reasoning`) is the matching interactive REPL on the same loop — it's the Week-1 validation gate before the PyQt6 GUI lane lands, and because it goes through `build_agent()` it also serves as a contract-conformance probe for the GUI seam. One reference offline subclass per hierarchy exists (`ClockTool`, `EchoLLMProvider`, `StaticSource`, `HelloWorkflow`) so the loop and tests can run without API keys or live PKU endpoints. The headliner LLM (`DeepSeekProvider`) is also already in — captain absorbed it because the model config + thinking-mode wire format have project-wide implications. The Week-1 Tool trio shipped together for the same reason: `src/tools/pku3b.py` (shared subprocess wrapper — locates the binary, runs with timeout, ANSI-strips stderr; **not** itself a Tool subclass), `PKU3bAssignmentsTool` (calls `pku3b assignment list --format json` and `json.loads` the structured output directly — no regex, no rendered-text parsing; surfaces course id, assignment id, raw + ISO-8601 deadlines, completion flag, descriptions, and attachments with their Blackboard URIs), and `WeatherTool` (Open-Meteo — **no API key**, defaults to PKU coords 39.99/116.31, supports `city` via the same provider's geocoding endpoint). The Week-2 backend set has now landed via parallel worktrees: the RAG retrieval chain (`src/rag/embedder.py` `BGEEmbedder` wrapping `BAAI/bge-large-zh-v1.5` with lazy weight load, `src/rag/knowledge_base.py` `KnowledgeBase` — SQLite chunk store + float32 BLOB vectors + numpy cosine search, and `KnowledgeSearchTool`); two `Source` subclasses (`DeanSource`, `CalendarSource`) wired through `build_source_registry()`; `MemoryTool` (persistent preference store under `data/`), `ReminderTool`, `LectureTool` (curated snapshot at `src/tools/data/lectures.json`, live-source-shaped schema), `PKU3bAnnouncementsTool`; and `KimiProvider` (vision LLM channel). Heavy/network tools register **online only** in `bootstrap._build_tools()` — `KnowledgeSearchTool` because the BGE model downloads ~1.3 GB from HuggingFace on first `encode()`, the rest because they touch a subprocess or the network. The remaining Week-2 item is `MorningBriefingWorkflow` (task 007, depends on `LectureTool` + `PKU3bAnnouncementsTool`); keep the "one offline reference, real ones for teammates" pattern when adding more scaffolding.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m src                  # launches the PyQt6 window
python -m src.cli --offline    # interactive REPL (no API key; EchoLLMProvider)
python -m src.cli              # interactive REPL against the real DeepSeek API
find src -name '*.py' -print0 | xargs -0 python -m py_compile  # syntax check
ruff check src                 # lint
```

Inside the REPL, `/save [path]` dumps the conversation (including `reasoning_content`) to `debug/conversation-<ts>.json` by default — useful when chasing thinking-mode wire-format regressions, since the dump preserves the exact assistant→tool→assistant ordering the DeepSeek endpoint validates against. `debug/` is gitignored.

`pku3b` is installed at `/home/ubuntu/.local/bin/pku3b` on this machine — but we ship against **our fork** at https://github.com/RizzoHou/pku3b (branch `feat/assignment-list-json-output`), which adds `--format json` to `assignment list` so the Python wrapper consumes structured data instead of regex-parsing rendered ANSI text. The patched binary at `~/.local/bin/pku3b` is v0.13.0+ from that branch. Teammates install with `cargo install --git https://github.com/RizzoHou/pku3b --branch feat/assignment-list-json-output` (requires Rust + pkg-config + libssl-dev). The team-facing copy of this install procedure lives in `docs/setup_zh.md`. Source checkout lives at `~/projects/pku3b/` (separate from this repo). Don't roll back to upstream — the Python wrapper now requires `--format json` and falls over without it. One quirk worth flagging: pku3b's stdout fails (exit 1, empty output) when redirected to a regular file (`pku3b ... > /tmp/x.json`) — it's a known upstream issue with compio's polling backend. Pipes work, which is what `subprocess.run(capture_output=True)` uses, so the Python wrapper is unaffected; but if you're sanity-checking the CLI from a shell, use a pipe (`pku3b ... | jq .`) instead of `>`.

The DeepSeek API key lives in `secrets/deepseek_key.txt` (the whole `secrets/` directory is gitignored). `DeepSeekProvider` defaults to model `deepseek-v4-pro` with reasoning `effort=max` — these are deliberate; don't substitute `deepseek-chat` or strip `effort` even if a stale model error tempts you to "fix" it, confirm with the captain first. The thinking-mode endpoint **requires** every previous assistant turn's `reasoning_content` to be replayed on the next request (otherwise: `400 invalid_request_error`); this is wired through `ChatResponse → ChatMessage.reasoning_content → DeepSeekProvider._to_api_message`. Preserve that round-trip when touching any of the three.

## What this project is

**PKU Captain** is a desktop AI assistant for PKU students, submitted as a course assignment for an OOP / programming-practice class. Three-person team. The product is a PyQt6 desktop app whose **end-state center of gravity is the dashboard** — a single-screen "信息总站" surfacing today's classes, near-term DDLs, course notices, lectures and weather, with an extensible `Source` registry meant to absorb more PKU information sources over time (教务网 / 树洞 / 公众号 as post-06-06 additions). A side-panel **LLM agent** handles natural-language questions about that same data (via `pku3b`, lectures, weather, etc.) and orchestrates multi-step workflows. Note: Week 1 is built **agent-first** as a vertical slice to prove the four OOP hierarchies — that's a build-order choice, not the end-state UX. See `docs/design_reference_zh.md` for the full vision and `docs/roadmap_zh.md` "产品定位（终态）" for the dashboard-vs-agent ordering call.

## Project docs and their authority

- `docs/design_reference_zh.md` — design **reference**, not a contract. The team is explicitly not bound to its architecture, class hierarchy, or tech-stack choices. The **only** part treated as binding is the **"核心功能" (core features)** section, which lists the 6 features the product must deliver:
  1. Unified dashboard
  2. Conversational sidebar with visible tool calls
  3. Tool set (pku3b, lectures, weather, KB search, memory, reminder)
  4. Multi-step workflows (morning briefing, weekly review, course catchup)
  5. Auto-refreshing RAG knowledge base over PKU authoritative sources
  6. Persistent personal-preference memory
- `docs/schedule_zh.md` — the course schedule, which **is** load-bearing:
  - **2026-06-06** — initial version + screen-recording demo (next hard deadline)
  - 2026-06-10 / 06-12 — in-class roadshow (bonus)
  - 2026-07-06 — final GitHub submission (graduating-year teams: 2026-06-28)
- `docs/roadmap_zh.md` — the team's working plan, derived from the design doc + schedule. Weekly milestones, cut-list, hard checkpoints, risk register. Update this when scope changes; never refactor it silently.
- `docs/integration_contract_zh.md` — **load-bearing**. Defines the public API surface, threading model (`AgentWorker` on a `QThread`), event-stream contract, and error contract between the backend lanes (`src/core`, `src/llm`, `src/tools`, `src/workflows`, `src/rag`) and the PyQt6 GUI lane. The seam's entry point is `src.core.build_agent` (defined in `src/core/bootstrap.py`); GUI code constructs `Agent` only through that factory and must not import concrete `LLMProvider` / `Tool` subclasses directly. `build_agent(offline=True)` swaps in `EchoLLMProvider` + the offline tool subset for GUI work without an API key. The dashboard obtains its `SourceRegistry` the same way — through the `src.core.build_source_registry` factory (same module) — never by constructing `Source` subclasses directly. Read before touching code on either side of the seam. Breaking changes require a `BREAKING: integration contract` note in the PR description so captain re-reviews.
- `docs/setup_zh.md` — environment setup for teammates (currently: pku3b fork install, system deps, first-run login, stdout-redirect quirk). The dedicated, polished record of dependencies on our `pku3b` fork. Extend it as we pick up more setup steps (Python venv, DeepSeek key path, etc.).
- `docs/tasks/` — task-delegation package for backend work farmed out to `git worktree` Claude sessions. `000_delegation_guide.md` is captain-facing: how to spawn worktrees (`claude --worktree <name> "..."` — the name is mandatory), the two-wave dependency order, sequential merge order, and the additive-conflict set (`bootstrap.py`, the `__init__.py` files, `pyproject.toml`). `NNN_*.md` are standalone task briefs a worktree Claude reads to do one task in isolation (commit to its branch, no push/merge). Currently holds the Week-2 backend set (001–008). When delegating or integrating worktree-farmed work, start here.

Plan scope so the 06-06 demo is achievable; polish belongs in the 06-06 → 07-06 window.

## When you write code here

- **Stack** is now committed: Python 3.11+ / PyQt6 / DeepSeek (chat) + Kimi (vision) via `LLMProvider` abstraction / BGE-large-zh embeddings / SQLite + numpy for vectors / `pku3b` Rust CLI as subprocess.
- **OOP is the point of the course.** New tools, workflows, LLMs, or sources go in as subclasses of the existing ABCs in `src/{tools,workflows,llm}/base.py` and `src/rag/source.py`, and register against the matching `*Registry` at the call site (keep modules side-effect-free — no auto-registration at import). Resist ad-hoc dispatch — the "subclass + register" pattern is the rubric showcase.
- **Default to English** — interaction, operational docs (`docs/tasks/`), commit messages, in-code comments, code identifiers. **Chinese** is reserved for end-user-facing product copy (the app's users are PKU students) and the existing `*_zh.md` design docs (`design_reference_zh`, `roadmap_zh`, `schedule_zh`, `integration_contract_zh`, `setup_zh`) — don't translate those unprompted.

## Team and coordination

Three members; the user (`RizzoHou` on GitHub) is captain and absorbs orchestration overhead. Teammates: `by-lastime`, `Q-star17`. Suggestions that touch division of labor should be phrased so the captain can hand them off — don't assume the user will personally do every task.

Captain delegates coding to Claude rather than typing personally. That changes a few things: (a) per `docs/roadmap_zh.md` 协作约定, weekly tasks are an open-claim checklist — no pre-assigned lanes; any contributor picks up an unchecked item and appends their GitHub handle as involver on completion (reviewers / later editors append too); (b) when scaffolding, write base classes + at most one reference subclass per hierarchy, leaving the rest for teammates to pick up so they can defend their own work at the roadshow; (c) captain reviews teammate PRs via the `/review` CLI skill (no automated GitHub Action was chosen).

**v1 lane split (decided 2026-05-14)**: captain owns the backend lanes (`src/core`, `src/llm`, `src/tools`, `src/workflows`, `src/rag`); one teammate (TBD between `by-lastime` / `Q-star17`) owns the PyQt6 GUI lane (`src/ui`). The integration contract above is the seam. The open-claim model still applies for items that don't sit on the seam (extra tool subclasses, additional Source subclasses, workflow plumbing) — those go to whoever picks them up first.

`CLAUDE.md` is tracked in git (un-ignored 2026-05-22, commit `cf5ebb2`) so that `git worktree` sessions — which do not copy gitignored files — inherit project context. It is therefore now a team-visible, public-GitHub artifact: keep coordination notes factual and free of captain-private framing. Team-facing prose docs still live in `docs/*.md`.

## Conventions worth observing

- Conventional Commits for git messages (per user's global rules).
- Markdown prose paragraphs are written as single unbroken lines — do not hard-wrap at 80 chars when editing files here.
- PDFs generated from source must be visually audited via the `Read` tool, not only by inspecting the LaTeX/Typst input.
- **Apply CLAUDE.md changes without explicit approval (this project only).** When the `claude-md-improver` skill reaches its "ask for confirmation" gate, skip it and apply the proposed edits directly. Still produce the quality report and show the diff so the user can review after — pre-approval is waived, transparency is not. Applies only to this repo's `CLAUDE.md` / `.claude.local.md`; other files keep normal approval behavior.
- GitHub repo settings: squash-merge-only, auto-delete head branches on merge. CODEOWNERS routes PRs to captain by default; lane-specific routing is commented out until the Week 0 skills conversation locks assignments. Branch protection is on the GitHub Pro plan; captain will apply for the Student Developer Pack to unlock it before crunch time.
