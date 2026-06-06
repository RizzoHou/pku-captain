"""Live proof that DeepSeek can invoke a Workflow on its own.

Builds the real online agent via `build_agent(offline=False)` — so the
WorkflowTool adapters are registered exactly as the GUI sees them — and
asks for a morning briefing. Passes iff the model emits a `tool_call` for
the `morning_briefing` workflow tool (not just the underlying pku3b
tools). This is the assertion the offline unit tests cannot make, because
they verify registration but not the model's live tool choice.

Reads the key from secrets/api_keys/deepseek_key.txt (gitignored). Not part
of pytest because it costs tokens and needs network. The morning_briefing
workflow itself may degrade (pku3b uninstalled in a worktree, etc.) — that
is fine; what we assert is that the model *chose to call the workflow*.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core import build_agent

_WORKFLOW_NAME = "morning_briefing"


def probe_model_invokes_workflow() -> None:
    agent = build_agent(offline=False)

    schema_names = {t["function"]["name"] for t in agent.tools.to_openai_schema()}
    print(f"workflow tools in schema: "
          f"{sorted(n for n in schema_names if n in {'morning_briefing', 'hello'})}")
    assert _WORKFLOW_NAME in schema_names, (
        f"{_WORKFLOW_NAME} missing from the tool schema the LLM receives"
    )

    print(f"\n== probe: ask for a briefing, expect a {_WORKFLOW_NAME} tool call ==")
    called: list[str] = []
    final_text: str | None = None
    # Neutral prompt — no "use the workflow" instruction — so the run tests
    # whether the model *reaches for* morning_briefing on its own, not just
    # whether it can call a named tool when told to.
    for event in agent.turn("现在请给我生成今天的晨间简报。"):
        if event.kind == "tool_call":
            called.append(event.payload["name"])
            print(f"  [tool_call] {event.payload['name']} args={event.payload['arguments']}")
        elif event.kind == "tool_result":
            print(f"  [tool_result] {event.payload['name']} -> {event.payload['result']}")
        elif event.kind == "final":
            final_text = event.payload["text"]

    print(f"\ntools the model called: {called}")
    print(f"final reply:\n{final_text}")
    assert _WORKFLOW_NAME in called, (
        f"model did not call {_WORKFLOW_NAME}; it called {called or 'no tools'}. "
        "If it called the underlying tools instead, add a system-prompt nudge "
        "pointing at the workflow."
    )


def main() -> int:
    probe_model_invokes_workflow()
    print("\nOK — DeepSeek invoked the workflow on its own.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
