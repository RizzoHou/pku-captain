"""Memory ↔ Agent integration: fold-into-responses and learn-from-conversation.

Uses a scripted LLM that records the exact message list it receives, so we
can assert what context the model actually saw — proving stored facts are
folded into the system prompt and that a `memory set` made mid-turn folds
forward into the very next LLM call. No network, fully deterministic.
"""

from __future__ import annotations

from typing import Any

from src.core import build_agent
from src.core.agent import Agent
from src.core.conversation import Conversation
from src.core.memory import MemoryStore
from src.llm.base import ChatMessage, ChatResponse, LLMProvider, ToolCall
from src.tools.base import ToolRegistry
from src.tools.memory import MemoryTool
from src.workflows.base import WorkflowRegistry


class ScriptedLLMProvider(LLMProvider):
    """Returns queued responses and records each message list it was given."""

    name = "scripted"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return ChatResponse(text="(done)")


def _system_text(messages: list[ChatMessage]) -> str:
    return next(m.content for m in messages if m.role == "system")


def _build(llm: LLMProvider, store: MemoryStore) -> Agent:
    tools = ToolRegistry()
    tools.register(MemoryTool(store=store))
    agent = Agent(
        llm=llm,
        tools=tools,
        workflows=WorkflowRegistry(),
        conversation=Conversation(),
        memory=store,
    )
    agent.conversation.add_system("BASE PROMPT")
    return agent


def test_existing_memory_is_folded_into_system_prompt(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.set("name", "侯宇泽")
    llm = ScriptedLLMProvider([ChatResponse(text="你好，侯宇泽")])
    agent = _build(llm, store)

    list(agent.turn("我是谁？"))

    system = _system_text(llm.calls[0])
    assert "BASE PROMPT" in system  # base prompt preserved
    assert "Known facts about the user" in system
    assert "侯宇泽" in system


def test_no_memory_leaves_system_prompt_untouched(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    llm = ScriptedLLMProvider([ChatResponse(text="ok")])
    agent = _build(llm, store)

    list(agent.turn("hi"))

    assert _system_text(llm.calls[0]) == "BASE PROMPT"


def test_learned_fact_folds_forward_within_turn(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    llm = ScriptedLLMProvider(
        [
            # Iteration 1: model decides to remember the user's name.
            ChatResponse(
                text="好的",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="memory",
                        arguments={"action": "set", "key": "name", "value": "侯宇泽"},
                    )
                ],
            ),
            # Iteration 2: model replies after the tool ran.
            ChatResponse(text="已记住你的名字"),
        ]
    )
    agent = _build(llm, store)

    events = list(agent.turn("我叫侯宇泽"))

    # The fact was persisted by the tool call.
    assert store.get("name").value == "侯宇泽"
    # Iteration 1 saw an empty store; iteration 2 saw the freshly learned fact.
    assert "侯宇泽" not in _system_text(llm.calls[0])
    assert "侯宇泽" in _system_text(llm.calls[1])
    # Exactly one system message — the block is merged, not appended.
    assert sum(1 for m in llm.calls[1] if m.role == "system") == 1
    # Turn still completed normally.
    assert events[-1].kind == "final"


def test_build_agent_shares_one_memory_store() -> None:
    # The load-bearing wiring: the Agent and the MemoryTool must hold the
    # *same* store, else mid-session writes never reach the next injection
    # and the whole feature silently no-ops. Offline so no API key is needed.
    agent = build_agent(offline=True)
    assert agent.memory is not None
    assert agent.memory is agent.tools.get("memory")._store


def test_memory_block_never_persists_to_conversation(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.json")
    store.set("name", "侯宇泽")
    llm = ScriptedLLMProvider([ChatResponse(text="ok")])
    agent = _build(llm, store)

    list(agent.turn("hi"))

    # The rendered block must not leak into stored history (GUI renders this).
    system_msgs = [m for m in agent.conversation.snapshot() if m.role == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0].content == "BASE PROMPT"
