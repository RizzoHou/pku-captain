from __future__ import annotations

import json

from src.core import bootstrap
from src.core.memory import MemoryStore
from src.tools.pku3b import Pku3bRun


def test_sync_pku3b_identity_memory_stores_stable_identity_fields(
    tmp_path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args):
        calls.append(list(args))
        return Pku3bRun(
            returncode=0,
            stdout=json.dumps(
                {
                    "name": "测试用户",
                    "student_id": "2300010000",
                    "department": "信息科学技术学院",
                    "speciality": "智能科学与技术",
                    "direction": None,
                    "student_type": "普通本科",
                    "user_identity": "学生",
                    "ethnic": "不应写入长期记忆",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(bootstrap, "run_pku3b", fake_run)
    store = MemoryStore(tmp_path / "memory.json")

    bootstrap._sync_pku3b_identity_memory(store)

    assert calls == [["identity", "--format", "json"]]
    assert store.get("identity.name").value == "测试用户"
    assert store.get("identity.student_id").value == "2300010000"
    assert store.get("identity.department").value == "信息科学技术学院"
    assert store.get("identity.speciality").value == "智能科学与技术"
    assert store.get("identity.student_type").value == "普通本科"
    assert store.get("identity.user_identity").value == "学生"
    assert store.get("identity.direction") is None
    assert store.get("ethnic") is None


def test_sync_pku3b_identity_memory_ignores_failed_cli(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        bootstrap,
        "run_pku3b",
        lambda _args: Pku3bRun(returncode=1, stdout="", stderr="needs otp"),
    )
    store = MemoryStore(tmp_path / "memory.json")

    bootstrap._sync_pku3b_identity_memory(store)

    assert store.list() == []


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
