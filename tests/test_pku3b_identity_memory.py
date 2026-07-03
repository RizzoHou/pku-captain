from __future__ import annotations

from pypku3b import Identity
from pypku3b.errors import AuthError

from src.core import bootstrap
from src.core.memory import MemoryStore


class _FakeClient:
    def __init__(self, identity=None, error=None):
        self._identity = identity
        self._error = error

    def get_identity(self, **_):
        if self._error is not None:
            raise self._error
        return self._identity


def _factory(identity=None, error=None):
    def make(**_kwargs):
        return _FakeClient(identity, error)

    return make


def test_sync_stores_stable_identity_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "stored_credentials", lambda _d: object())
    identity = Identity(
        name="测试用户",
        student_id="2300010000",
        department="信息科学技术学院",
        speciality="智能科学与技术",
        direction=None,
        student_type="普通本科",
        user_identity="学生",
        ethnic="不应写入长期记忆",
    )
    store = MemoryStore(tmp_path / "memory.json")

    bootstrap._sync_pku3b_identity_memory(store, client_factory=_factory(identity))

    assert store.get("identity.name").value == "测试用户"
    assert store.get("identity.student_id").value == "2300010000"
    assert store.get("identity.department").value == "信息科学技术学院"
    assert store.get("identity.speciality").value == "智能科学与技术"
    assert store.get("identity.student_type").value == "普通本科"
    assert store.get("identity.user_identity").value == "学生"
    assert store.get("identity.direction") is None
    # ethnic is not one of the synced fields.
    assert store.get("ethnic") is None
    assert store.get("identity.ethnic") is None


def test_sync_ignores_auth_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "stored_credentials", lambda _d: object())
    store = MemoryStore(tmp_path / "memory.json")

    bootstrap._sync_pku3b_identity_memory(
        store, client_factory=_factory(error=AuthError("needs otp"))
    )

    assert store.list() == []


def test_sync_skips_without_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "stored_credentials", lambda _d: None)
    called: list[int] = []

    def factory(**_kwargs):
        called.append(1)
        raise AssertionError("should not build a client without credentials")

    store = MemoryStore(tmp_path / "memory.json")
    bootstrap._sync_pku3b_identity_memory(store, client_factory=factory)

    assert called == []
    assert store.list() == []


def test_sync_skips_when_already_synced(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "stored_credentials", lambda _d: object())
    called: list[int] = []

    def factory(**_kwargs):
        called.append(1)
        raise AssertionError("sync-once guard should skip the portal login")

    store = MemoryStore(tmp_path / "memory.json")
    store.set("identity.name", "已存在")

    bootstrap._sync_pku3b_identity_memory(store, client_factory=factory)

    assert called == []
    assert store.get("identity.name").value == "已存在"


def test_online_build_agent_runs_identity_sync(monkeypatch, tmp_path) -> None:
    from src.llm.echo import EchoLLMProvider
    from src.tools.base import ToolRegistry

    store = MemoryStore(tmp_path / "memory.json")
    called = []

    monkeypatch.setattr(bootstrap, "_build_llm", lambda *, offline: EchoLLMProvider())
    monkeypatch.setattr(bootstrap, "MemoryStore", lambda: store)
    monkeypatch.setattr(bootstrap, "_build_tools", lambda **_kwargs: ToolRegistry())
    monkeypatch.setattr(
        bootstrap,
        "_sync_pku3b_identity_memory",
        lambda memory: called.append(memory),
    )

    agent = bootstrap.build_agent(offline=False)

    assert called == [store]
    assert agent.memory is store
