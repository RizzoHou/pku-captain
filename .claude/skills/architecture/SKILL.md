---
name: architecture
description: Audit and update ARCHITECTURE.md when a change altered the project's structure. Fire ONLY on a structural change — a new module or package, a new or moved abstraction boundary, a new Tool/Workflow/LLMProvider/Source subclass that changes the map, a new registry, a changed runtime data flow (turn loop, dashboard refresh, event stream), a new external dependency, or a moved seam. Do NOT fire for behavior-only changes, bug fixes, copy edits, or new code that slots into an existing box. Keeps the human auditor's box-and-arrow map of the system true to reality.
---

# architecture — maintain ARCHITECTURE.md

`ARCHITECTURE.md` (repo root) is the **structural map** — the box-and-arrow view of what talks to what and where the boundaries are. It is the thing `CLAUDE.md` is bad at: CLAUDE.md is dense *invariant* prose ("keep the store shared", "don't revert accumulation to replace") that you cannot read structure out of. This file is the structure, so the human can audit the invariants in context.

## Boundary — do not duplicate CLAUDE.md

| File | Holds | Shape |
|---|---|---|
| `ARCHITECTURE.md` | **Structure** — components, boundaries, the seam, data flows, external deps | Map / diagram |
| `CLAUDE.md` "Repo status" | **Rules + invariants** — what must stay true, what not to break | Prose constraints |
| `docs/integration_contract_zh.md` | The GUI↔backend **seam contract** (binding, Chinese) | API surface |

ARCHITECTURE.md describes *shape*; CLAUDE.md describes *rules*; neither restates the other. Cross-reference instead of copying. When they would say the same thing, ARCHITECTURE.md links to the CLAUDE.md invariant.

## When to fire (structural changes only)

Fire when the change moved a box or an arrow:

- New package/module, or a module split/merged.
- New abstraction boundary, or one relocated (e.g. state threaded through a new service, a new global, a new seam factory).
- New `Tool` / `Workflow` / `LLMProvider` / `Source` subclass that the map should name, or a new `*Registry`.
- Changed runtime data flow — the `Agent.turn()` event stream, dashboard refresh fan-out, memory folding, doc-base vision read, session persistence.
- New external dependency (a CLI sibling, an API endpoint, a system binary).

Do **not** fire for: a bug fix, a behavior tweak, GUI copy, a test, or new code that drops cleanly into an existing box without changing the map.

## Procedure (audit-then-update, like claude-md-improver)

1. Read `ARCHITECTURE.md` fully.
2. Compare each section against the actual change you just made and the current tree (`find src -name '*.py'`, the registries in `src/*/base.py`, `build_agent` in `src/core/bootstrap.py`).
3. Update only the sections the change touched — a component box, an arrow, a data-flow step, the external-deps list, the seam. Keep ASCII diagrams legible; prefer editing an existing diagram over adding a parallel one.
4. If you added a box, say in one line what it is and what it talks to. If you moved a boundary, update both sides.
5. Keep it a *map*, not a tutorial — no code walkthroughs, no invariant prose (that's CLAUDE.md).

## Do not

- Do not copy invariants from CLAUDE.md; link to them.
- Do not let the diagram drift — a stale architecture map is worse than none, because the human audits it and trusts it.
- Do not fire on non-structural changes; an over-eager update churns the file and trains the human to stop reading the diff.
