# DEVCHANGELOG.md

The **development decision log** — why changes were made, not what shipped. Maintained by the `devchangelog` skill, append-only, newest first.

**Boundary.** `CHANGELOG.md` records *what shipped* (user-facing, per merge). This file records *why + what the agent did* (decisions, tradeoffs, actions) for the human auditor. A decision ("chose X over Y because Z") goes here; a feature line ("added the calendar button") goes in CHANGELOG. The same change can produce one entry in each on different axes.

---

## 2026-06-29 — Agentic auditing machinery (DEVCHANGELOG / ARCHITECTURE / VERIFICATION + skills)

- **What**: added three repo-root audit artifacts and three project-level skills to maintain them; wired a plan-gate convention into CLAUDE.md.
- **Decision**: relocate the human's verification off the code (needs stack knowledge) onto stack-agnostic artifacts (handoff doc `docs/external/...`). Three skills, not one combined — single-responsibility matches the repo's subclass-and-register aesthetic — but each fires by **change type** (devchangelog ~every change, architecture only on structural change, verification on user-visible/release-critical change), not all-every-task, to avoid four mandatory post-task rituals alongside `claude-md-improver`.
- **Decision**: keep DEVCHANGELOG separate from CHANGELOG on a why-vs-what axis; keep ARCHITECTURE separate from CLAUDE.md on a structure-vs-rules axis. Cross-reference, never restate.
- **Decision**: track `.claude/skills/` (un-ignored just that subtree; repo is PRIVATE) so the machinery is durable team/worktree state, consistent with how `CLAUDE.md` is tracked. Rest of `.claude/` stays gitignored.
- **Decision**: plan-gate stays a CLAUDE.md convention, not a fourth skill (user capped skills at three; machinery is experimental, to be packaged as a Claude plugin once mature).
- **Files**: `.claude/skills/{devchangelog,architecture,verification}/SKILL.md`, `ARCHITECTURE.md`, `DEVCHANGELOG.md`, `VERIFICATION.md`, `.gitignore`, `CLAUDE.md`.
- **Verify**: VERIFICATION.md → "Agentic auditing machinery" + "Credential pre-release audit".
