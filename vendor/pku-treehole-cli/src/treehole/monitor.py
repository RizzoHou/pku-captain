"""Poll the 关注 list, diff reply counts against stored state, emit the holes
that gained replies — and, by default, the new comment text itself.

The platform never pushes followed-hole updates, so poll+diff is the only model.

Two-layer diff:
  * The *trigger* is the per-hole `reply` count: diff_holes (pure, unit-tested,
    no network) flags only holes whose count INCREASED.
  * The *content* of the new replies is then fetched per triggered hole using a
    `cid` cursor (the last comment id we have already shown, persisted in state).
    comment/list is oldest-first with monotonically-increasing `cid`, so the new
    replies are exactly those with `cid > last_cid` (and they live at the tail of
    the last page). On a hole's first observed growth there is no cursor yet, so
    we fall back to the newest `delta` comments, then record the cursor.

Known limitation 1: the *trigger* is still count-based, so a delete+add between
two polls that nets to the SAME reply count produces no update and stays invisible
— the cursor does not change that. What the cursor *does* fix: when the count
net-increases despite a deletion (e.g. -1 +3 = +2), `cid > last_cid` surfaces all
3 genuinely-new replies, where a naive "last delta" tail would show only 2.

Known limitation 2: a transient comment-fetch failure degrades that hole to
count-only for the poll (see Monitor._enrich). With a prior cursor this self-heals
— the next growth re-fetches everything past the cursor. But on a hole's FIRST
growth (no cursor yet) the reply baseline still advances to the new count, so the
missed comment text is not recovered on the next poll: the count is reported, the
text for that one batch is lost.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import requests

from .client import TreeholeClient
from .errors import APIError
from .state import StateMap, StateStore

# How many comments to fetch per page, and the max new comments to *display* per
# hole. The cap keeps polling gentle: a hole that gained 900 replies becomes one
# last-page fetch, not 36 pages. The cursor (last_cid) still advances fully.
COMMENT_LIMIT = 25
COMMENT_CAP = 10


@dataclass(frozen=True)
class Comment:
    """A single new reply, for display only — never persisted to state."""

    cid: int
    text: str | None = None
    name_tag: str | None = None
    timestamp: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Update:
    """A followed hole that gained replies since the last check.

    `text` is the hole body; `new_comments` are the new replies, both from the
    live fetch (for display) — neither is ever persisted to state. `new_comments`
    is empty when comment fetching is disabled or a transient fetch failed (the
    count delta is still reported)."""

    pid: str
    old_reply: int
    new_reply: int
    delta: int
    text: str | None = None
    new_comments: list[Comment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # recurses into Comment


def diff_holes(prev: StateMap, holes: list[dict[str, Any]], now: int) -> tuple[list[Update], StateMap]:
    """Pure diff. Returns (updates, next_state).

    * Emit only when a previously-seen hole's reply count INCREASED.
    * First sight of a hole (cold start / newly followed) → record baseline, no emit.
    * Reply count decreased or unchanged → update state silently (deleted comments).
    * next_state is rebuilt from the current list, so unfollowed holes drop out.
    * The comment cursor (`last_cid`) is carried forward verbatim from prev; the
      enrichment step (Monitor.check) advances it for holes that grew. Cold-start
      entries get no `last_cid` key, so existing state stays backward-compatible.
    """
    updates: list[Update] = []
    next_state: StateMap = {}
    for h in holes:
        pid = str(h.get("pid"))
        reply = int(h.get("reply") or 0)
        entry: dict[str, Any] = {"reply": reply, "checked_at": now}
        old = prev.get(pid)
        if old is not None and old.get("last_cid") is not None:
            entry["last_cid"] = old["last_cid"]  # carry the comment cursor forward
        next_state[pid] = entry
        if old is None:
            continue  # baseline only
        old_reply = int(old.get("reply") or 0)
        if reply > old_reply:
            updates.append(Update(
                pid=pid, old_reply=old_reply, new_reply=reply,
                delta=reply - old_reply, text=h.get("text"),
            ))
    return updates, next_state


class Monitor:
    def __init__(self, client: TreeholeClient, store: StateStore):
        self.client = client
        self.store = store

    def check(self, *, only: set[str] | None = None, now: int | None = None,
              fetch_comments: bool = True) -> list[Update]:
        """Fetch holes, diff, optionally fetch the new comments, persist, return
        updates.

        `only` restricts monitoring to a watchlist of pids. Instead of paging the
        whole 关注 list, each watched hole is fetched directly via hole/get — far
        gentler at a tight poll interval when the watchlist is small, and it can
        watch any pid (followed or not). With `only`, state is *merged*: only the
        watched pids are rewritten, every other stored hole is preserved untouched.
        That means a watchlist run never clobbers a full-follow-list state file,
        and a watched hole that is transiently unreachable keeps its baseline (so
        it does not silently re-baseline and swallow the next real update).

        Raises (NeedSMSVerification / AuthError) propagate — a monitor must fail
        loud, never return [] as if "all caught up" when locked out. A *per-hole*
        comment-fetch hiccup (APIError / network) degrades only that hole to
        count-only; it does not abort the poll. State is persisted only after the
        whole fetch succeeds (exceptions bubble before save)."""
        prev = self.store.load()
        now = int(time.time()) if now is None else now
        if only:
            holes = self._fetch_watch(only)
            updates, watched_next = diff_holes(prev, holes, now)
            next_state = {**prev, **watched_next}  # merge: untouched pids preserved
        else:
            holes = self.client.followed_all()
            updates, next_state = diff_holes(prev, holes, now)
        if fetch_comments:
            updates = [self._enrich(u, prev, next_state) for u in updates]
        self.store.save(next_state)
        return updates

    def _fetch_watch(self, only: set[str]) -> list[dict[str, Any]]:
        """Fetch each watched pid via hole/get. A per-hole transient failure
        (APIError / network / missing hole) is skipped this tick — check()'s merge
        then preserves that hole's stored baseline. SMS/auth errors still propagate
        (they subclass AuthError, not APIError) so the monitor fails loud."""
        holes: list[dict[str, Any]] = []
        for pid in sorted(only, key=str):
            try:
                h = self.client.hole(pid)
            except (APIError, requests.exceptions.RequestException):
                continue
            if isinstance(h, dict) and h.get("pid") is not None:
                holes.append(h)
        return holes

    # --- comment enrichment ---------------------------------------------------
    def _enrich(self, u: Update, prev: StateMap, next_state: StateMap) -> Update:
        """Attach the new comments to one update and advance its cursor in
        next_state. A transient per-hole failure degrades to count-only."""
        raw = (prev.get(u.pid) or {}).get("last_cid")
        prev_cid = int(raw) if raw is not None else None
        try:
            comments, max_cid = self._new_comments(
                u.pid, new_reply=u.new_reply, prev_cid=prev_cid, delta=u.delta)
        except (APIError, requests.exceptions.RequestException):
            # NeedSMSVerification / AuthError are NOT caught here — they must fail
            # loud (they subclass AuthError, not APIError).
            return u
        if max_cid:
            next_state[u.pid]["last_cid"] = max_cid
        return replace(u, new_comments=comments)

    def _new_comments(
        self, pid: str, *, new_reply: int, prev_cid: int | None, delta: int,
        limit: int = COMMENT_LIMIT, cap: int = COMMENT_CAP,
    ) -> tuple[list[Comment], int]:
        """Return (new comments oldest-first, newest cid seen).

        comment/list is oldest-first with ascending cid, so the newest replies sit
        at the tail of the last page. We locate that page, then walk backward
        collecting comments with `cid > prev_cid` (or, with no cursor, the newest
        `delta`), stopping at the cursor / `delta` / `cap` to stay gentle."""
        located = self._last_comment_page(pid, new_reply, limit)
        if located is None:
            return [], (prev_cid or 0)
        page, cmts = located
        max_cid = max(int(c.get("cid") or 0) for c in cmts)
        collected: list[dict[str, Any]] = []  # oldest-first overall
        while True:
            if prev_cid is not None:
                sel = [c for c in cmts if int(c.get("cid") or 0) > prev_cid]
            else:
                sel = list(cmts)
            collected = sel + collected
            oldest = int(cmts[0].get("cid") or 0)
            done = (
                page <= 1
                or (prev_cid is not None and oldest <= prev_cid)
                or (prev_cid is None and len(collected) >= delta)
                or len(collected) >= cap
            )
            if done:
                break
            page -= 1
            cmts = self.client.comments(pid, page=page, limit=limit)
            if not cmts:  # below the tail there should be none; stop defensively
                break
        if prev_cid is None:
            collected = collected[-delta:]  # only the newest delta on first growth
        shown = collected[-cap:]
        comments = [
            Comment(cid=int(c.get("cid") or 0), text=c.get("text"),
                    name_tag=c.get("name_tag"), timestamp=c.get("timestamp"))
            for c in shown
        ]
        return comments, max_cid

    def _last_comment_page(
        self, pid: str, new_reply: int, limit: int
    ) -> tuple[int, list[dict[str, Any]]] | None:
        """Locate the last non-empty comment page (where the newest replies are).

        Start from ceil(new_reply/limit); reply count usually equals comment count
        but may drift, so nudge forward while the page is full and walk back while
        it is empty. Past-end pages return [] (code 20000), so this terminates.
        Returns (page, comments) or None if the hole has no comments."""
        page = max(1, math.ceil(new_reply / limit))
        cmts = self.client.comments(pid, page=page, limit=limit)
        while len(cmts) == limit:  # count underestimated → real tail is further on
            nxt = self.client.comments(pid, page=page + 1, limit=limit)
            if not nxt:
                break
            page, cmts = page + 1, nxt
        while not cmts and page > 1:  # count overestimated (deleted) → step back
            page -= 1
            cmts = self.client.comments(pid, page=page, limit=limit)
        return (page, cmts) if cmts else None
