# Correctness

Taste that keeps behavior right — especially under concurrency and bad input.

## Eliminate special cases; make the edge case the normal case

The best fix for a branch that handles "the first element" or "the empty poll" is to reshape the data so the branch disappears (Torvalds' good-taste argument). Fewer branches, fewer places for a bug to hide.

- **Prefer**: `merge_treehole_updates` unions by id, so an empty poll is just a no-op union.
- **Avoid**: a replace-on-poll path plus a special case to stop it wiping the list — the accumulate model needs no such case.

## Accumulate, don't replace, for delta feeds

Poll/delta sources (treehole, dean inbox) union into a persisted store and stay visible until the user acts — never overwrite from the latest poll, or a reply vanishes on the next empty poll. See `src/tools/treehole_updates.py` (`TreeholeInboxStore`, `merge_treehole_updates`) and `src/tools/dean_updates.py` (`DeanInboxStore`, `merge_dean_updates`).

## Isolate errors so one failure can't sink the batch

Where work fans out (dashboard refresh), each unit swallows its own exception and reports independently — one card's failure never crashes the dashboard or corrupts a sibling (`DashboardWorker._invoke`). Build env/state per call (`os.environ.copy()`), never mutate global state a sibling reads.

## Guard invariants explicitly, and name why

When a sequence can go invalid, add the guard with its reason: `drop_incomplete_tool_calls` trims a trailing `assistant(tool_calls)` with no results because the endpoint 400s forever otherwise; session switching no-ops mid-turn. A one-line guard with a stated reason beats a silent assumption.

## Decode at the right boundary

Both providers' `stream_chat` iterate raw bytes then UTF-8-decode — `iter_lines(decode_unicode=True)` corrupts multi-byte CJK at chunk boundaries. When bytes cross a buffer boundary, decode after reassembly, not per chunk.

## Tests are real, small, and prove the invariant

A test asserts the actual invariant — a learned fact folds into the next call; a serial refresh can't pass the `threading.Barrier` test — not merely that code runs. Offline reference subclasses keep them network-free. One test that would fail if the invariant broke beats three that wouldn't.
