---
name: devchangelog
description: Append a development decision-log entry to DEVCHANGELOG.md after making a change. Use after completing any non-trivial change that involved a decision, a tradeoff, or a structural action — i.e. nearly every coding task. Records WHY (chose X over Y because Z) and what was done, session-grained and append-only. This is distinct from the changelog skill (which writes user-facing release notes in CHANGELOG.md); DEVCHANGELOG is the agent's internal decision trail for the human auditor. Skip only for pure reads, questions, or trivial no-op edits.
---

# devchangelog — maintain DEVCHANGELOG.md

`DEVCHANGELOG.md` (repo root) is the **decision log** — the prose trail the human auditor reads to keep their mental model current without reading code. The agent is memoryless across sessions and will undo a day-one decision on day three unless the reasoning is written down. This file is that memory.

## Boundary — do not confuse with CHANGELOG.md

| File | Axis | Audience | Grain |
|---|---|---|---|
| `CHANGELOG.md` | **What shipped** — user-facing features/fixes | Team / future users | Per merge |
| `DEVCHANGELOG.md` | **Why + what the agent did** — decisions, tradeoffs, actions | The human auditor (Rizzo) | Per change / session |

If your entry reads like a feature description ("added a calendar reminder button"), it belongs in CHANGELOG. If it reads like a rationale ("chose osascript over EventKit because no native dep"), it belongs here. The same change often produces one line in each, on different axes. Never narrate features here.

## When to fire

After any change that involved a **decision, tradeoff, or structural action**. That is almost every coding task. Skip only genuinely trivial turns (reads, questions, typo fixes, no-op edits).

## Format

Newest entries at the **top** (reverse-chronological), append-only. Use today's date (the harness provides `currentDate`). One entry per change/session:

```markdown
## YYYY-MM-DD — <short title>

- **What**: one line on what changed.
- **Decision**: chose X over Y because Z. (Omit if no real fork was taken.)
- **Files**: key files touched (paths, not exhaustive).
- **Verify**: pointer to the VERIFICATION.md entry, or "n/a".
```

Keep each bullet to one line. Empiricality over prose: state the decision and the reason, not the journey. If there was no real fork, drop the Decision line rather than inventing one. A reader should grasp an entry in five seconds.

## Procedure

1. Read the current top of `DEVCHANGELOG.md` to match style and avoid duplicating an entry.
2. Compose the entry from the change you just made — pull the *why* from your actual reasoning this session, not a reconstruction.
3. Insert it directly below the file header, above the previous newest entry.
4. If the change also altered structure (new module, boundary, registry, data flow, external dep), the **architecture** skill should run too — flag it; this skill does not touch ARCHITECTURE.md.

## Do not

- Do not restate CHANGELOG feature copy here.
- Do not write multi-paragraph entries — terse, one line per bullet.
- Do not backfill old changes you didn't make this session.
