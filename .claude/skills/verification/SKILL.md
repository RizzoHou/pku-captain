---
name: verification
description: Add human-executable verification steps to VERIFICATION.md after a change. Fire after any change with user-visible behavior, any release-critical change, or anything automated tests cannot fully cover (GUI behavior, real network round-trips, credential handling, the running app). Produces concrete copy-pasteable steps a non-coding human runs to confirm the change works — the verification floor placed where the human can reach it. This is the manual layer that complements pytest; it does not duplicate the automated suite. Distinct from the global `verify` skill (which runs the app itself); this skill WRITES the steps for the human to run.
---

# verification — maintain VERIFICATION.md

`VERIFICATION.md` (repo root) is the **human-owned verification floor**. The human is the architect but does not read code, so verification is relocated off the code and onto **observable behavior**: copy-pasteable commands and "do this → expect this" steps the human executes to confirm a change is real. "Looks plausible" is the danger zone, not the safe zone — this file is how the human gets past plausible to confirmed.

## What goes here vs. pytest

- **pytest** covers what automation can assert (`pytest tests/`). Run it; reference it; do **not** re-script it here.
- **VERIFICATION.md** covers what automation can't reach: GUI behavior, real DeepSeek/Kimi round-trips, subprocess/credential paths, the running app, anything needing a human eye. The credential audit (handoff doc: the one path to verify by hand) lives here.

A good step is readable without stack knowledge: `python -m src --online`, then "open 文档库, click 让 Captain 阅读 → expect page images answered in chat." A bad step is `assert dispatch._route == X`.

## When to fire

After any change that is user-visible, release-critical, or beyond pytest's reach. Skip pure-internal refactors fully covered by green tests (note in DEVCHANGELOG that tests suffice).

## File structure — a queue, not a graveyard

Two sections. New work lands in **Pending**; the human moves it to **Verified** (or you collapse it) once they've run it. The unreviewed delta is always at the top.

```markdown
## Pending verification

### YYYY-MM-DD — <change title>
**Proves**: <the user-visible behavior or property this confirms>
**Steps**:
1. `<exact command>` → expect `<exact observable result>`
2. In the app: <action> → expect <observable>
**Automated**: `pytest tests/test_foo.py` (what it already covers)

## Verified

<one-line collapsed entries the human has signed off, newest first>
```

## How to write steps

- **Exact and copy-pasteable**: real commands with real flags (`python -m src --online`, `python scripts/smoke_deepseek.py`, `pytest tests/test_x.py`), not "run the app."
- **Observable expectations**: state what the human should *see* (a value, a rendered card, a Chinese error toast, no crash), not an internal assertion.
- **State what it proves**: one line tying the steps to the user-visible property.
- **Offline vs online**: note which mode each step needs (`--offline` needs no key; `--online` needs `secrets/api_keys/*`).
- **Negative cases**: where it matters, include the failure path ("network down → shows a message, doesn't crash").

## Procedure

1. Read `VERIFICATION.md`; reuse its structure.
2. Add a Pending entry for the change you just made.
3. Run any automated portion yourself first (`pytest`, smoke) and cite it — never hand the human a step you haven't confirmed at least compiles/passes where you can.
4. Leave the manual steps for the human; do not mark them Verified yourself — only the human moves an entry to Verified.

## Do not

- Do not duplicate pytest cases as manual steps.
- Do not write a step whose expected result you're guessing — run it or label it explicitly as unverified.
- Do not let Pending grow unbounded; once the human confirms, collapse the entry into Verified.
