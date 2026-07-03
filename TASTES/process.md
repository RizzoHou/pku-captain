# Process

Taste about how work moves, not what the code says.

## Plan before non-trivial code (plan-gate)

For any non-trivial or structural change, state the plan in plain prose first — files, approach, what could break, assumptions — and let it be approved before coding. Push boundary decisions (a new service, a new global) up into the plan; leave idioms (which Qt signal, which API call) down in the code. Trivial changes skip the gate.

## Small, honest, conventional commits

Conventional Commits format. Commit after completing a task. Report outcomes faithfully — if a test fails, say so with the output; if a step was skipped, say that; don't claim done-and-verified without having verified.

## Keep the auditing artifacts true

This repo is auditable by a non-coding architect through prose + observable behavior. Fire the right artifact by change type, not every task: `ARCHITECTURE.html` (structure changed), `DEVCHANGELOG.md` (a decision/tradeoff — nearly every change), `VERIFICATION.md` (user-visible / release-critical / beyond-pytest), `CHANGELOG.md` (per merge). Cross-reference; never restate.

## Worktrees commit but don't push

A `claude --worktree` session (cwd under `.claude/worktrees/`, or a branch named `worktree*`) commits to its own branch and stops — no merge, rebase, push, or PR. The captain integrates. Outside a worktree, default-branch pushes are pre-authorized.

## Credentials leak invisibly — audit by hand

The app works while leaking a secret, so behavior tests won't catch it. Redact secrets from anything reaching LLM context or logs (`src/tools/redact.py`), inject creds per-call, and run the manual credential audit in `VERIFICATION.md` before a release. Never commit `secrets/`.

## Verify by running, not only by reading

After a change, show the terminal commands that verify it; for user-visible behavior, run the app or a smoke test rather than trusting the diff. `scripts/smoke_deepseek.py` is mandatory after `core/`/`llm/`/wire-format changes.
