# TASTES

Prescriptive coding-taste guidance for PKU Captain — how code here should look and feel. Distilled mostly from this codebase's own hard-won lessons, lightly seasoned with a few external principles. Maintained actively by the `tastes` project skill.

## Why this exists

The captain isn't a coder by trade and can't dictate code taste directly. So the taste lives here instead: a durable, referenceable layer that keeps the codebase coherent as it grows and as different contributors (and Claude sessions) touch it.

## Scope — what belongs here vs elsewhere

TASTES is the *aesthetic / pattern* layer: timeless "prefer X over Y, because Z" guidance. It is deliberately distinct from the repo's other prose artifacts:

| Artifact | Answers | Grain |
|---|---|---|
| **TASTES/** | How should code look and feel? | Timeless principle |
| `CLAUDE.md` | What are the live rules and invariants? | Operational rule |
| `ARCHITECTURE.html` | How is the system laid out? | Structure map |
| `DEVCHANGELOG.md` | Why did we decide X on date D? | Dated decision |
| `CHANGELOG.md` | What shipped? | Release note |

Rule of thumb: a general "this is good taste" principle belongs here; a specific live invariant ("keep the memory store shared") belongs in `CLAUDE.md`; a dated one-off decision belongs in `DEVCHANGELOG.md`. **Cross-reference those files, never restate them.**

## Topics

- [code-structure.md](code-structure.md) — modules, boundaries, the subclass+register idiom, imports, deep interfaces.
- [naming-and-style.md](naming-and-style.md) — naming, comments, the English/Chinese split, formatting.
- [correctness.md](correctness.md) — error isolation, eliminating special cases, guards and invariants, encoding, tests that are real.
- [process.md](process.md) — plan-gate, commits, the auditing artifacts, worktrees, credential hygiene.

## How this is maintained

The `tastes` project skill (`.claude/skills/tastes/`) fires when a session surfaces a reusable taste lesson (capture it in the right topic file) and audits for drift against `CLAUDE.md` on request. Files stay short — a handful of concrete prefer/avoid rules each, every rule earning its place. New tastes are grounded in this codebase first; external principles enter only as a thin supplement.
