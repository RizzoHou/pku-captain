# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo status

Pre-code: only `docs/` exists. No source tree, no build system, no tests yet. The next contributor (human or AI) is expected to scaffold the project. There is therefore nothing to build, lint, or run — record commands here as they are introduced.

## What this project is

**PKU Captain** is a desktop AI assistant for PKU students, submitted as a course assignment for an OOP / programming-practice class. Three-person team. The product is a PyQt6 desktop app where an LLM agent answers questions about PKU-specific data (assignments via `pku3b`, lectures, canteens, weather, official notices) and runs multi-step workflows. See `docs/design_reference_zh.md` for the full vision.

## Two documents, very different authority

- `docs/design_reference_zh.md` — design **reference**, not a contract. The team is explicitly not bound to its architecture, class hierarchy, or tech-stack choices. The **only** part treated as binding is the **"核心功能" (core features)** section, which lists the 6 features the product must deliver:
  1. Unified dashboard
  2. Conversational sidebar with visible tool calls
  3. Tool set (pku3b, canteen, lectures, weather, KB search, memory, reminder)
  4. Multi-step workflows (morning briefing, weekly review, course catchup)
  5. Auto-refreshing RAG knowledge base over PKU authoritative sources
  6. Persistent personal-preference memory
- `docs/schedule_zh.md` — the course schedule, which **is** load-bearing:
  - **2026-06-06** — initial version + screen-recording demo (next hard deadline)
  - 2026-06-10 / 06-12 — in-class roadshow (bonus)
  - 2026-07-06 — final GitHub submission (graduating-year teams: 2026-06-28)

Plan scope so the 06-06 demo is achievable; polish belongs in the 06-06 → 07-06 window.

## When you write code here

- **Language / stack** is open to revision but the design doc's suggestion is Python 3.11 + PyQt6, DeepSeek (chat) + Kimi (vision) via an LLM-provider abstraction, BGE-large-zh embeddings, SQLite + numpy for vectors, `pku3b` (Rust CLI) called as a subprocess.
- **OOP is the point of the course.** When introducing new tools, data sources, LLMs, or workflows, prefer subclassing + registry over ad-hoc dispatch. The design doc names four parallel hierarchies (`Tool`, `Workflow`, `LLMProvider`, `Source`) — keep that "subclass + register" shape unless there's a concrete reason not to.
- **Chinese is the primary language** for product copy, design docs, and likely most in-code comments and commit-body prose. Code identifiers should stay English. Don't translate the existing Chinese docs unprompted.

## Team and coordination

Three members; the user (`RizzoHou` on GitHub) is captain and absorbs orchestration overhead. Teammates: `by-lastime`, `Q-star17`. Suggestions that touch division of labor should be phrased so the captain can hand them off — don't assume the user will personally do every task.

## Conventions worth observing

- Conventional Commits for git messages (per user's global rules).
- Markdown prose paragraphs are written as single unbroken lines — do not hard-wrap at 80 chars when editing files here.
- PDFs generated from source must be visually audited via the `Read` tool, not only by inspecting the LaTeX/Typst input.
