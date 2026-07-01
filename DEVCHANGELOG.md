# DEVCHANGELOG.md

The **development decision log** — why changes were made, not what shipped. Maintained by the `devchangelog` skill, append-only, newest first.

**Boundary.** `CHANGELOG.md` records *what shipped* (user-facing, per merge). This file records *why + what the agent did* (decisions, tradeoffs, actions) for the human auditor. A decision ("chose X over Y because Z") goes here; a feature line ("added the calendar button") goes in CHANGELOG. The same change can produce one entry in each on different axes.

---

## 2026-07-01 — TASTES/ coding-taste directory + tastes skill

- **What**: added `TASTES/` (README + four broad topic files: `code-structure`, `naming-and-style`, `correctness`, `process`) capturing prescriptive coding-taste guidance, plus a `tastes` project skill to maintain it.
- **Decision**: seed **codebase-first** — rules are distilled from this repo's own lessons (subclass+register, side-effect-free imports, accumulate-don't-replace, raw-byte CJK decode) with external principles (Ousterhout deep modules, Torvalds eliminate-special-cases) as a thin supplement only; generic internet boilerplate (SOLID/DRY lectures) explicitly excluded. Project-specific tastes are higher-value than generic ones and stay true to the code.
- **Decision**: **a few broad files, not many narrow ones** (captain's call) — four topics keep the surface scannable and maintenance low.
- **Decision**: TASTES sits on a distinct *taste* axis — cross-references CLAUDE.md (live invariants) / DEVCHANGELOG (dated decisions) / ARCHITECTURE (structure), never restates them; the skill enforces that boundary plus a drift audit against CLAUDE.md.
- **Decision**: docs/tooling, not user-facing → DEVCHANGELOG entry only, **no CHANGELOG** (mirrors the agentic-auditing-machinery precedent); not a code structural change, so ARCHITECTURE/VERIFICATION don't fire.
- **Files**: `TASTES/{README,code-structure,naming-and-style,correctness,process}.md`, `.claude/skills/tastes/SKILL.md`.
- **Verify**: n/a (prose artifacts; no runtime behavior).

## 2026-06-29 — Credential redaction at the tool boundary + CLAUDE.md prune

- **What**: added `src/tools/redact.py` (`redact(text, secrets)`); `run_plib` and `TreeholeAuthService` now strip injected/held credentials from any error string before it becomes a `ToolResult.error`. Compressed three verbose CLAUDE.md paragraphs to bring the file back under the 39k budget (38,561, below the 38,879 baseline).
- **Decision**: redact at the **tool/subprocess boundary**, not centrally in `Agent.turn()` — keeps `core` free of secret-path knowledge and strips exactly what each tool injects/holds. pku3b is **not** covered: its portal password lives in pku3b's own `cfg.toml` and never enters our process, so there is no value to strip (documented in `redact.py`, not faked).
- **Decision**: fail safe — `redact` over-redacts a short secret rather than risk under-redacting, and skips empty/whitespace secrets (an empty `str.replace` would shred the text).
- **Decision**: the CLAUDE.md prune **compresses in place**, it does not relocate the macOS gotchas to ARCHITECTURE.md — gotchas are *rules* and must keep firing in CLAUDE.md; relocating them would break the structure-vs-rules boundary. Only step-by-step elaboration was cut; every load-bearing rule kept.
- **Files**: `src/tools/{redact,plib_materials,treehole_updates}.py`, `tests/test_redact.py`, `CLAUDE.md`.
- **Verify**: VERIFICATION.md → "Credential pre-release audit" (fix applied; `pytest tests/test_redact.py`).

## 2026-06-29 — Agentic auditing machinery (DEVCHANGELOG / ARCHITECTURE / VERIFICATION + skills)

- **What**: added three repo-root audit artifacts and three project-level skills to maintain them; wired a plan-gate convention into CLAUDE.md.
- **Decision**: relocate the human's verification off the code (needs stack knowledge) onto stack-agnostic artifacts (handoff doc `docs/external/...`). Three skills, not one combined — single-responsibility matches the repo's subclass-and-register aesthetic — but each fires by **change type** (devchangelog ~every change, architecture only on structural change, verification on user-visible/release-critical change), not all-every-task, to avoid four mandatory post-task rituals alongside `claude-md-improver`.
- **Decision**: keep DEVCHANGELOG separate from CHANGELOG on a why-vs-what axis; keep ARCHITECTURE separate from CLAUDE.md on a structure-vs-rules axis. Cross-reference, never restate.
- **Decision**: track `.claude/skills/` (un-ignored just that subtree; repo is PRIVATE) so the machinery is durable team/worktree state, consistent with how `CLAUDE.md` is tracked. Rest of `.claude/` stays gitignored.
- **Decision**: plan-gate stays a CLAUDE.md convention, not a fourth skill (user capped skills at three; machinery is experimental, to be packaged as a Claude plugin once mature).
- **Files**: `.claude/skills/{devchangelog,architecture,verification}/SKILL.md`, `ARCHITECTURE.md`, `DEVCHANGELOG.md`, `VERIFICATION.md`, `.gitignore`, `CLAUDE.md`.
- **Verify**: VERIFICATION.md → "Agentic auditing machinery" + "Credential pre-release audit".
