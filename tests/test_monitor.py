"""Diff logic + comment-cursor walk — the genuinely new, bug-prone code. No network."""

from treehole.errors import APIError
from treehole.monitor import Monitor, diff_holes
from treehole.state import StateStore


def _hole(pid, reply, text="t"):
    return {"pid": pid, "reply": reply, "text": text, "likenum": 0}


class FakeClient:
    """Serves canned comment pages (oldest-first, ascending cid) and a settable
    followed_all. Records the pages requested so tests can assert the walk stayed
    bounded; `fail_pids` makes comment fetches raise APIError for those holes."""

    def __init__(self, pages, holes=None, fail_pids=()):
        self._pages = pages  # {page_int: [comment dicts]}
        self.holes = list(holes or [])
        self.fail_pids = {str(p) for p in fail_pids}
        self.requested = []

    def comments(self, pid, *, page=1, limit=25):
        if str(pid) in self.fail_pids:
            raise APIError("simulated comment fetch failure", code=42411)
        self.requested.append(page)
        return list(self._pages.get(page, []))

    def followed_all(self, **k):
        return list(self.holes)


def _cmt(cid):
    return {"cid": cid, "text": f"c{cid}", "name_tag": "X", "timestamp": cid}


def _monitor(pages):
    return Monitor(FakeClient(pages), store=None)  # store unused by _new_comments


# limit=3 pages so fullness/pagination is exercised without 25-item fixtures.
PAGES = {1: [_cmt(10), _cmt(11), _cmt(12)],
         2: [_cmt(13), _cmt(14), _cmt(15)],
         3: [_cmt(16), _cmt(17)]}  # last page, partial


def test_cold_start_records_baseline_no_updates():
    holes = [_hole(1, 5), _hole(2, 0)]
    updates, state = diff_holes({}, holes, now=100)
    assert updates == []
    assert state == {"1": {"reply": 5, "checked_at": 100}, "2": {"reply": 0, "checked_at": 100}}


def test_reply_increase_emits():
    prev = {"1": {"reply": 5, "checked_at": 1}}
    updates, _ = diff_holes(prev, [_hole(1, 8)], now=200)
    assert len(updates) == 1
    u = updates[0]
    assert (u.pid, u.old_reply, u.new_reply, u.delta) == ("1", 5, 8, 3)
    assert u.text == "t"


def test_decrease_and_same_are_silent_but_update_state():
    prev = {"1": {"reply": 5, "checked_at": 1}, "2": {"reply": 9, "checked_at": 1}}
    updates, state = diff_holes(prev, [_hole(1, 3), _hole(2, 9)], now=300)
    assert updates == []  # deleted comments / unchanged → no emit
    assert state["1"]["reply"] == 3 and state["2"]["reply"] == 9


def test_unfollowed_hole_drops_from_state():
    prev = {"1": {"reply": 5, "checked_at": 1}, "2": {"reply": 5, "checked_at": 1}}
    _, state = diff_holes(prev, [_hole(1, 5)], now=400)  # hole 2 no longer followed
    assert set(state) == {"1"}


def test_text_is_not_in_persisted_state():
    _, state = diff_holes({}, [_hole(1, 5, text="secret anonymous speech")], now=1)
    assert "text" not in state["1"]


def test_diff_carries_last_cid_forward_but_not_on_cold_start():
    # cold start: no cursor key (backward-compatible with legacy state files)
    _, state = diff_holes({}, [_hole(1, 5)], now=1)
    assert "last_cid" not in state["1"]
    # existing cursor survives an unchanged poll
    prev = {"1": {"reply": 5, "checked_at": 1, "last_cid": 999}}
    _, state = diff_holes(prev, [_hole(1, 5)], now=2)
    assert state["1"]["last_cid"] == 999


# --- comment cursor walk (_new_comments) ----------------------------------

def test_cursor_hit_mid_last_page():
    m = _monitor(PAGES)
    comments, max_cid = m._new_comments("1", new_reply=8, prev_cid=16, delta=1, limit=3, cap=10)
    assert [c.cid for c in comments] == [17]   # only cid > 16
    assert max_cid == 17                        # newest cid, for the next cursor
    assert m.client.requested == [3]            # one page; did not walk back


def test_cursor_spans_multiple_pages():
    m = _monitor(PAGES)
    comments, max_cid = m._new_comments("1", new_reply=8, prev_cid=13, delta=4, limit=3, cap=10)
    assert [c.cid for c in comments] == [14, 15, 16, 17]
    assert max_cid == 17
    assert m.client.requested == [3, 2]         # walked back exactly to the cursor


def test_no_cursor_falls_back_to_newest_delta():
    m = _monitor(PAGES)
    comments, max_cid = m._new_comments("1", new_reply=8, prev_cid=None, delta=2, limit=3, cap=10)
    assert [c.cid for c in comments] == [16, 17]  # newest delta only
    assert max_cid == 17
    assert m.client.requested == [3]


def test_display_cap_bounds_walk_and_output():
    m = _monitor(PAGES)
    comments, max_cid = m._new_comments("1", new_reply=8, prev_cid=None, delta=99, limit=3, cap=3)
    assert [c.cid for c in comments] == [15, 16, 17]  # capped to the newest 3
    assert max_cid == 17
    assert 1 not in m.client.requested               # stopped before the oldest page


def test_forward_nudge_when_reply_count_underestimates():
    # reply=6 → ceil(6/3)=2, but page 2 is full so the real tail is page 3.
    m = _monitor(PAGES)
    comments, max_cid = m._new_comments("1", new_reply=6, prev_cid=16, delta=1, limit=3, cap=10)
    assert [c.cid for c in comments] == [17]
    assert max_cid == 17
    assert m.client.requested[:2] == [2, 3]          # nudged forward to the tail


def test_no_comments_returns_empty():
    m = _monitor({})  # hole with no comments
    comments, max_cid = m._new_comments("1", new_reply=3, prev_cid=5, delta=3, limit=3, cap=10)
    assert comments == []
    assert max_cid == 5  # cursor unchanged when nothing fetched


# --- Monitor.check round trip (the seam an agent consumer depends on) ------
# These use the real StateStore + default COMMENT_LIMIT (25), so all the canned
# comments live on page 1.

def test_check_round_trip_persists_and_reuses_cursor(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    client = FakeClient({1: [_cmt(c) for c in (10, 11, 12, 13, 14)]}, holes=[_hole(1, 5)])
    mon = Monitor(client, store)

    # poll 1: cold-start baseline — no updates, no cursor yet
    assert mon.check(now=1) == []
    assert "last_cid" not in store.load()["1"]

    # grows 5 -> 8; first growth has no cursor -> newest `delta` (3) comments
    client._pages = {1: [_cmt(c) for c in (10, 11, 12, 13, 14, 15, 16, 17)]}
    client.holes = [_hole(1, 8)]
    updates = mon.check(now=2)
    assert [c.cid for c in updates[0].new_comments] == [15, 16, 17]
    saved = store.load()["1"]
    assert saved["last_cid"] == 17 and isinstance(saved["last_cid"], int)  # persisted as int

    # repeat poll, identical data -> no count change -> nothing re-displayed
    assert mon.check(now=3) == []
    assert store.load()["1"]["last_cid"] == 17  # cursor preserved across the no-op poll

    # grows 8 -> 9; the stored cursor (17) is reused, so ONLY the new cid shows
    client._pages = {1: [_cmt(c) for c in (10, 11, 12, 13, 14, 15, 16, 17, 18)]}
    client.holes = [_hole(1, 9)]
    updates = mon.check(now=4)
    assert [c.cid for c in updates[0].new_comments] == [18]
    assert store.load()["1"]["last_cid"] == 18


def test_check_isolates_per_hole_comment_failure(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    client = FakeClient({1: [_cmt(c) for c in (20, 21, 22, 23, 24, 25)]},
                        holes=[_hole(1, 3), _hole(2, 3)])
    mon = Monitor(client, store)
    assert mon.check(now=1) == []  # baseline both

    # both grow; the comment fetch for hole 1 raises APIError
    client.holes = [_hole(1, 6), _hole(2, 6)]
    client.fail_pids = {"1"}
    updates = {u.pid: u for u in mon.check(now=2)}

    assert set(updates) == {"1", "2"}
    assert updates["1"].new_comments == [] and updates["1"].delta == 3  # degraded to count-only
    assert [c.cid for c in updates["2"].new_comments] == [23, 24, 25]   # other hole unaffected
    saved = store.load()
    assert saved["1"]["reply"] == 6 and "last_cid" not in saved["1"]    # save still happened
    assert saved["2"]["reply"] == 6 and saved["2"]["last_cid"] == 25
