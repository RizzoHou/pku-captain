"""Watchlist mode of Monitor.check (only=...): fetch-each via hole/get, merge
state. No network."""

from treehole.errors import APIError
from treehole.monitor import Monitor
from treehole.state import StateStore


def _hole(pid, reply, text="t"):
    return {"pid": pid, "reply": reply, "text": text, "likenum": 0}


class WatchClient:
    """Serves per-pid holes via hole(); fail_pids raise APIError. followed_all is
    forbidden — watchlist mode must never page the whole follow list."""

    def __init__(self, holes_by_pid, fail_pids=()):
        self._holes = {str(k): v for k, v in holes_by_pid.items()}
        self.fail_pids = {str(p) for p in fail_pids}
        self.fetched = []

    def hole(self, pid):
        pid = str(pid)
        self.fetched.append(pid)
        if pid in self.fail_pids:
            raise APIError("simulated hole fetch failure", code=42411)
        return self._holes[pid]

    def comments(self, pid, *, page=1, limit=25):
        return []  # fetch_comments=False in these tests

    def followed_all(self, **k):
        raise AssertionError("watchlist mode must not call followed_all")


def test_watchlist_only_fetches_watched_holes(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    client = WatchClient({1: _hole(1, 8), 2: _hole(2, 9), 3: _hole(3, 1)})
    mon = Monitor(client, store)
    # baseline only holes 1 and 2
    assert mon.check(only={"1", "2"}, fetch_comments=False) == []
    assert sorted(client.fetched) == ["1", "2"]  # never touched hole 3

    # hole 1 grows; still only watching {1,2}
    client._holes["1"] = _hole(1, 12)
    updates = mon.check(only={"1", "2"}, fetch_comments=False)
    assert [(u.pid, u.delta) for u in updates] == [("1", 4)]


def test_watchlist_preserves_unwatched_state(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    store.save({"99": {"reply": 5, "checked_at": 1, "last_cid": 42}})  # from a full run
    client = WatchClient({1: _hole(1, 3)})
    mon = Monitor(client, store)
    mon.check(only={"1"}, fetch_comments=False)
    saved = store.load()
    assert saved["99"] == {"reply": 5, "checked_at": 1, "last_cid": 42}  # untouched
    assert saved["1"]["reply"] == 3


def test_watchlist_transient_failure_preserves_baseline(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    client = WatchClient({1: _hole(1, 5)})
    mon = Monitor(client, store)
    assert mon.check(only={"1"}, fetch_comments=False) == []  # baseline reply=5

    # next tick: hole 1 would have grown, but the fetch fails
    client._holes["1"] = _hole(1, 9)
    client.fail_pids = {"1"}
    updates = mon.check(only={"1"}, fetch_comments=False)
    assert updates == []                          # skipped, not emitted
    assert store.load()["1"]["reply"] == 5        # baseline preserved (not lost)

    # fetch recovers next tick -> the growth (5 -> 9) is surfaced, nothing missed
    client.fail_pids = set()
    updates = mon.check(only={"1"}, fetch_comments=False)
    assert [(u.pid, u.old_reply, u.new_reply) for u in updates] == [("1", 5, 9)]


def test_watchlist_cold_start_is_silent(tmp_path):
    store = StateStore(str(tmp_path / "s.json"))
    client = WatchClient({7: _hole(7, 4)})
    mon = Monitor(client, store)
    assert mon.check(only={"7"}, fetch_comments=False) == []
    assert store.load()["7"]["reply"] == 4
