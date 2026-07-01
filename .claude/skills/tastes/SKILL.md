---
name: tastes
description: Maintain the TASTES/ directory — the project's prescriptive coding-taste guidance. Fire when a session surfaced a reusable taste/pattern lesson worth capturing (a recurring "prefer X over Y"), or when asked to review, refresh, or add coding tastes. Records timeless taste principles distilled codebase-first; distinct from DEVCHANGELOG (dated decisions) and CLAUDE.md (live invariants). Skip for one-off decisions, pure reads, and trivial edits.
---

# tastes — maintain TASTES/

`TASTES/` is the project's **coding-taste layer**: timeless, prescriptive "prefer X over Y, because Z" guidance, distilled mostly from this codebase's own lessons. The captain can't dictate code taste directly, so this directory is where taste is captured and kept coherent as the codebase and its contributors grow.

## Boundary — do not confuse with the other prose artifacts

| Artifact | Answers | Grain |
|---|---|---|
| **TASTES/** | How should code look and feel? | Timeless principle |
| `CLAUDE.md` | Live rules and invariants | Operational rule |
| `DEVCHANGELOG.md` | Why decided X on date D | Dated decision |
| `ARCHITECTURE.md` | System layout | Structure map |

If it's a general taste principle, it's TASTES. If it's a specific live invariant or a dated one-off, it's not — cross-reference those files, never restate them.

## Structure

- `TASTES/README.md` — purpose, the boundary table, topic index.
- Four broad topic files, lowercased: `code-structure.md`, `naming-and-style.md`, `correctness.md`, `process.md`. Keep to a few broad files, not many narrow ones — add a fifth only when a genuinely new axis appears, and never split a file just because it grew a little.

## When to fire

- A session surfaced a **reusable** taste lesson — a "prefer X over Y" that will recur (a pattern that worked, a mistake worth not repeating). Capture it in the right topic file.
- The captain asks to review, refresh, or add coding tastes.

Skip when the lesson is a one-off decision (that's DEVCHANGELOG) or a live invariant (that's CLAUDE.md), and skip pure reads / trivial edits.

## Procedure

1. Pick the topic file the lesson belongs to (README's index maps them).
2. Add or tighten a rule: a one-line **prefer** / **avoid** with a one-line rationale, plus a real file reference from this repo where one exists. Codebase-first — a concrete `src/...` example beats an abstract principle.
3. Keep each file short — a handful of rules. If a rule duplicates CLAUDE.md, replace it with a cross-reference instead of a copy.
4. Update `README.md`'s index only if a topic file was added or removed.

## Drift audit (when invoked to review)

Read TASTES against `CLAUDE.md` and skim recent `DEVCHANGELOG.md` entries: promote a recurring taste that's implicit in CLAUDE.md into a TASTES rule (leave a cross-reference), and delete or fix any TASTES rule a code change has made false.

## Do not

- Do not restate CLAUDE.md invariants or DEVCHANGELOG decisions — link them.
- Do not let files sprawl — prune weak rules; every rule earns its place.
- Do not add generic internet boilerplate (SOLID/DRY lectures) — external principles enter only as a thin supplement to a codebase-grounded rule.
