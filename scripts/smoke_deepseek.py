"""End-to-end smoke test for the Agent kernel against the real DeepSeek API.

Runs two probes:
  1. plain chat — verifies model name + effort parameter are accepted.
  2. agent turn with ClockTool — verifies tool-call serialization, tool
     dispatch, and follow-up assistant turn all survive a real round-trip.

Reads the key from secrets/deepseek_key.txt (gitignored). Not part of
pytest because it costs tokens and needs network.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core import Agent, Conversation
from src.llm import ChatMessage, DeepSeekProvider
from src.tools import ClockTool
from src.tools.base import ToolRegistry
from src.workflows.base import WorkflowRegistry


def _load_key() -> str:
    path = REPO_ROOT / "secrets" / "deepseek_key.txt"
    return path.read_text(encoding="utf-8").strip()


def probe_plain_chat(provider: DeepSeekProvider) -> None:
    print("== probe 1: plain chat ==")
    resp = provider.chat(
        [ChatMessage(role="user", content="Reply with the single word: pong.")]
    )
    print(f"text:        {resp.text!r}")
    print(f"tool_calls:  {resp.tool_calls}")
    assert resp.text, "expected non-empty text from plain chat"


def probe_agent_with_tool(provider: DeepSeekProvider) -> None:
    print("\n== probe 2: agent turn with ClockTool ==")
    tools = ToolRegistry()
    tools.register(ClockTool())
    agent = Agent(
        llm=provider,
        tools=tools,
        workflows=WorkflowRegistry(),
        conversation=Conversation(),
    )
    agent.conversation.add_system(
        "You are a terse assistant. If a tool can answer the user's question, "
        "use it. Otherwise reply directly."
    )

    saw_tool_call = False
    final_text: str | None = None
    for event in agent.turn("What time is it right now? Use the clock tool."):
        print(f"  [{event.kind}] {event.payload}")
        if event.kind == "tool_call":
            saw_tool_call = True
        if event.kind == "final":
            final_text = event.payload["text"]

    assert saw_tool_call, "expected the model to call clock"
    assert final_text, "expected a final assistant reply"


def main() -> int:
    key = _load_key()
    provider = DeepSeekProvider(api_key=key)
    print(f"using model={provider.model!r}, effort={provider.effort!r}")
    probe_plain_chat(provider)
    probe_agent_with_tool(provider)
    print("\nOK — smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
