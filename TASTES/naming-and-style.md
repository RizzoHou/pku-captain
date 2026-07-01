# Naming and style

## Match the surrounding code

Write code that reads like the file it lives in — same naming, comment density, and idioms. Consistency within a module beats importing a personal style.

## Comments: minimal, and about *why*

Prefer a self-explaining name over a comment that narrates the code. Reserve comments for the non-obvious — a wire-format quirk, a workaround, an invariant not visible locally (e.g. "reasoning_content must be replayed or the endpoint 400s"). No decorative section banners.

## Language split is a hard rule

English for everything structural: code identifiers, in-code comments, commit messages, operational docs (`docs/tasks/`), and interaction. **Chinese is reserved for end-user-facing product copy** (the app's users are PKU students) and the existing `*_zh.md` design docs — don't translate those unprompted.

- **Prefer**: identifiers `upcoming_assignments`, `merge_treehole_updates`; a Chinese button label `加入日历`.
- **Avoid**: Chinese identifiers or comments; English text shown to the end user in the GUI.

## Short names are fine when unambiguous

Short identifiers are good where the meaning is local and clear; reach for a longer name only when the short one would mislead. A well-named thing needs no comment.

## Markdown prose is single unbroken lines

In markdown files, never hard-wrap a prose paragraph — one paragraph is one line. Use lists and tables for scanning; don't wrap at 80 columns.
