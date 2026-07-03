from pypku3b.cache import Cache
from pypku3b.config import load_credentials


def test_load_credentials_from_dir(tmp_path):
    (tmp_path / "id").write_text("2500000000\n")
    (tmp_path / "password").write_text("s3cret\n")
    creds = load_credentials(tmp_path)
    assert creds is not None
    assert creds.username == "2500000000"
    assert creds.password == "s3cret"


def test_load_credentials_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PKU_USERNAME", "envuser")
    monkeypatch.setenv("PKU_PASSWORD", "envpass")
    (tmp_path / "id").write_text("diruser")
    (tmp_path / "password").write_text("dirpass")
    creds = load_credentials(tmp_path)
    assert creds == type(creds)("envuser", "envpass")


def test_load_credentials_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("PKU_USERNAME", raising=False)
    monkeypatch.delenv("PKU_PASSWORD", raising=False)
    # An empty dir yields no credentials (and ~/.config fallback is unlikely
    # to exist in CI). Assert it does not read the given dir's absent files.
    assert load_credentials(tmp_path) is None


def test_cache_hit_miss_and_force(tmp_path):
    cache = Cache(tmp_path, default_ttl=3600)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"v": calls["n"]}

    first = cache.get_or_compute("k", compute)
    second = cache.get_or_compute("k", compute)
    assert first == second == {"v": 1}
    assert calls["n"] == 1  # second was a cache hit

    # force=True bypasses the read and recomputes.
    third = cache.get_or_compute("k", compute, force=True)
    assert third == {"v": 2}
    assert calls["n"] == 2

    # A subsequent normal read hits the freshly-written value.
    assert cache.get_or_compute("k", compute) == {"v": 2}
    assert calls["n"] == 2


def test_cache_disabled_always_computes():
    cache = Cache(None)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return calls["n"]

    assert cache.get_or_compute("k", compute) == 1
    assert cache.get_or_compute("k", compute) == 2
