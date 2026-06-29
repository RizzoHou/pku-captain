# PKU Captain — Serious Agentic SWE Workflow (Handoff)

**Purpose of this doc.** This is context for a Claude Code session. It captures a workflow for producing *maintainable, good-taste* code from agentic coding — not just *feasible* code — under a hard constraint: the human (Rizzo) is the architect but does **not** have time to learn the underlying stack idioms, and wants implementation details handled by the agent. PKU Captain is about to be released formally to all PKUers within days. Use this as the seed for setting up the project's working agreement (CLAUDE.md, plan-gate, tests, etc.). Rizzo will discuss specifics from here.

---

## Project context

PKU Captain: a Python/PyQt6 desktop AI agent for the PKU community. Integrates DeepSeek + Kimi, a RAG layer (bge-large-zh embeddings), a polymorphic tool registry wrapping a Rust CLI (pku3b, which accesses the PKU teaching network), and a persistent memory subsystem. Architecture is Rizzo's own design and stays that way. Imminent public release to real student users.

---

## The core idea (the spine of everything below)

Trivial agentic coding produces *feasible but not maintainable* code because the agent faithfully optimizes the objective it was handed — "make it work" — and **maintainability is invisible to that objective.** The reward arrives the moment the feature runs and tests pass; naming, boundaries, locality, and not-over-engineering don't change "looks done," so they get systematically under-invested.

"Serious" agentic SWE is therefore the craft of **changing the objective the agent actually optimizes** — by supplying taste as explicit rules, structuring the work so taste is forced, and keeping the human in the loop as the thing that carries judgment.

The key move for someone who won't learn the stack: **verification cannot be deleted, only relocated.** The agent already hits *feasible* on its own; the gap to *tasteful* is by definition the part process alone doesn't reach. So the human still verifies — but verification is moved **off the code** (which needs stack knowledge) **onto artifacts that are stack-agnostic prose or observable behavior:** plans, decision logs, change summaries, audit reports, and the running app. The human never reads lines; the human reads the shadows the code casts.

---

## The workflow

1. **A standing constitution — `CLAUDE.md`.** This is where Rizzo's judgment lives when he isn't watching. Two parts: (a) an **architecture map** — box-and-arrow of what talks to what and where the boundaries are — so the agent stops reinventing structure; (b) a **taste ruleset**: prefer explicit over clever, flat over nested, no abstraction before the third use, no config flag without a caller, no error handling for impossible errors, names describe intent not type, strong YAGNI default (the agent's instinct is to over-engineer with speculative flexibility and defensive layers — rein it in). **Mandate in this file that the agent explains its plan in plain prose before writing code.** That one rule converts human control from line-reading into plan-reading.

2. **A plan-gate on every non-trivial change.** Agent writes a short plan first — which files, what approach, what could break, what it's assuming — and the human approves the **plan, not the diff**. A plan is stack-agnostic and readable without Qt/RAG knowledge ("I'll wrap the network call in a retry and surface failures as a toast"). This is the load-bearing step for a human who skips the stack.

3. **Machine taste-enforcement the agent runs itself.** ruff (lint + format), pyright or mypy (types), pytest (behavior), wired so the agent runs all three after every change and goes green before claiming done. This is the substitute for human line-reading: automated judgment with a hard red/green signal the agent self-corrects against. **Verify the harness actually fails** when something is wrong — break something on purpose and confirm the suite goes red; agents will cheerfully write suites that pass unconditionally.

4. **Behavior-level acceptance tests the human owns.** For each feature, the human states user-visible behavior ("ask about a course → returns the right course; network down → shows a message, doesn't crash"); the agent writes the test; the human sanity-checks that the test asserts something *real* (`assert course_name in response` is readable without knowing dispatch internals). This is the verification floor, placed where the human can reach it.

5. **A decision log.** A few lines per structural call: "chose X over Y because Z." The agent is memoryless across sessions and *will* undo a day-one decision on day three because it can't see the reasoning. The log is prose the human reads, and it keeps the human's mental model current without reading code.

6. **Small increments + plain-language summary.** Keep diffs small enough to hold in your head. Even when the human won't read the diff, the agent emits a five-bullet "here's what I did," then the human runs the app and checks behavior. Summary + running app = the audit surface. Note: *"looks plausible" is the danger zone, not the safe zone* — plausible is exactly the threshold the agent optimizes to clear.

---

## The credential exception (do not delegate this one)

The pku3b path touches **real student credentials**, and credential leakage is **invisible to black-box / behavior testing** — the app works perfectly while silently logging a password or folding it into the LLM context shipped to DeepSeek/Kimi. No acceptance test catches this because nothing user-visible breaks. So "verify behavior only" fails here.

The time-cheap fix that still skips the stack: run a **focused audit pass** instead of learning the code. Prompt: *"List every place a credential is read, stored, written to a log, or sent over the network, and show me the list."* The human then reads the **report** (stack-agnostic prose). **Must-fix before release:** anything sending credentials into an LLM context or a log file. This is the one path to verify by hand.

---

## Boundaries vs. implementation (the precise line)

"Implementation details belong to the agent" is correct — but **abstraction boundaries are architecture wearing implementation's clothes.** When the agent decides "I'll make this a separate service" or "I'll thread this state through a global," that gets mentally filed under "implementation detail," escapes review, and becomes the cruft.

The plan-gate's real job: **drag boundary decisions UP** into the plan layer where the human sees them, while leaving genuine idiom-level choices (how to use a Qt signal, which embedding call) **DOWN** in the agent layer where they belong. Same division of labor Rizzo wants — drawn one notch more precisely.

---

## Status: settled vs. open

**Settled (the working agreement above):** plan-before-code, plan-gate over diff-gate, self-running lint/type/test harness, human-owned behavior tests, decision log, small increments + summaries, hand-audited credential path, boundaries-up/idioms-down.

**Open for discussion in Claude Code (Rizzo will drive):**
- Drafting the actual `CLAUDE.md` (architecture map + taste rules) tuned to Captain's real repo layout.
- A concrete plan-template wired to the tool-registry / RAG / memory structure.
- Setting up + proving the ruff/pyright/pytest harness.
- The pre-release credential/hardening audit, plus general personal→released concerns (real config not hardcoded, legible failures, environments differing from the dev machine).

**Suggested first action for Claude Code:** ask Rizzo for the current repo layout, then draft `CLAUDE.md` and the plan-template against it rather than generically.
