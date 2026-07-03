---
name: architecture
description: Audit and update ARCHITECTURE.html when a change altered the project's structure. Fire ONLY on a structural change — a new module or package, a new or moved abstraction boundary, a new Tool/Workflow/LLMProvider/Source subclass that changes the map, a new registry, a changed runtime data flow (turn loop, dashboard refresh, event stream), a new external dependency, or a moved seam. Do NOT fire for behavior-only changes, bug fixes, copy edits, or new code that slots into an existing box. Keeps the human auditor's box-and-arrow map of the system true to reality.
---

# architecture — maintain ARCHITECTURE.html

`ARCHITECTURE.html` (repo root) is the **structural map** — the box-and-arrow view of what talks to what and where the boundaries are, rendered as a self-contained HTML page (open it in a browser for the visual view). It is the thing `CLAUDE.md` is bad at: CLAUDE.md is dense *invariant* prose ("keep the store shared", "don't revert accumulation to replace") that you cannot read structure out of. This file is the structure, so the human can audit the invariants in context.

## Boundary — do not duplicate CLAUDE.md

| File | Holds | Shape |
|---|---|---|
| `ARCHITECTURE.html` | **Structure** — components, boundaries, the seam, data flows, external deps | Map / diagram |
| `CLAUDE.md` "Repo status" | **Rules + invariants** — what must stay true, what not to break | Prose constraints |
| `docs/integration_contract_zh.md` | The GUI↔backend **seam contract** (binding, Chinese) | API surface |

ARCHITECTURE.html describes *shape*; CLAUDE.md describes *rules*; neither restates the other. Cross-reference instead of copying. When they would say the same thing, ARCHITECTURE.html links to the CLAUDE.md invariant.

## When to fire (structural changes only)

Fire when the change moved a box or an arrow:

- New package/module, or a module split/merged.
- New abstraction boundary, or one relocated (e.g. state threaded through a new service, a new global, a new seam factory).
- New `Tool` / `Workflow` / `LLMProvider` / `Source` subclass that the map should name, or a new `*Registry`.
- Changed runtime data flow — the `Agent.turn()` event stream, dashboard refresh fan-out, memory folding, doc-base vision read, session persistence.
- New external dependency (a CLI sibling, an API endpoint, a system binary).

Do **not** fire for: a bug fix, a behavior tweak, GUI copy, a test, or new code that drops cleanly into an existing box without changing the map.

## Procedure (audit-then-update, like claude-md-improver)

1. Read `ARCHITECTURE.html` fully.
2. Compare each section against the actual change you just made and the current tree (`find src -name '*.py'`, the registries in `src/*/base.py`, `build_agent` in `src/core/bootstrap.py`).
3. Update only the sections the change touched — a component box, an arrow, a data-flow step, the external-deps list, the seam. The five `<section>`s (`#lanes` / `#oop` / `#flows` / `#deps` / `#xref`) mirror the old numbered headings; edit inside the existing markup — a `.band`/`.box` in the layered diagram, a `<tr>` in a table, a step in `pre.flow` or `.flowlist`. Prefer editing an existing element over adding a parallel one.
4. If you added a box, say in one line what it is and what it talks to (a new `.box`, `<tr>`, or `.flowlist` item). If you moved a boundary, update both sides.
5. Keep it a *map*, not a tutorial — no code walkthroughs, no invariant prose (that's CLAUDE.md).

## Editing the HTML (keep it self-contained)

- **One file, no external assets.** All CSS is in the single inline `<style>` block; no scripts, fonts, images, or CDN links. Keep it that way so the page opens straight from disk (`file://`) with no build step or network.
- **Reuse the existing classes** rather than inventing markup: `.band` (a lane) with `.band-label` / `.band-note`, `.box` (a component; `.full` spans the row), `.flowdown` (the `↓` connector between bands), `.backend-grid .box .tag` (the `core/`/`llm/`… rows), `pre.flow` (the turn-loop listing), `.flowlist` (the other data-flow steps), `.tablewrap > table` (the two tables), `.callout`, `ul.xref`. Colours come from the `:root` CSS variables (PKU-red theme, mirrors `src/ui/styles.py`) and already have a `prefers-color-scheme: dark` variant — don't hard-code hex.
- **Stay valid HTML.** Escape literal `<`/`>`/`&` in prose as `&lt;`/`&gt;`/`&amp;` (e.g. `data/sessions/&lt;id&gt;.json`). After a non-trivial edit, sanity-check the render — a headless browser screenshot or opening it locally beats trusting the diff, per the same visual-audit discipline as PDFs.

## Do not

- Do not copy invariants from CLAUDE.md; link to them.
- Do not let the diagram drift — a stale architecture map is worse than none, because the human audits it and trusts it.
- Do not fire on non-structural changes; an over-eager update churns the file and trains the human to stop reading the diff.
