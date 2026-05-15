"""Interactive REPL for the PKU Captain agent.

Lets the captain (and anyone else) drive the backend end-to-end before the
PyQt6 GUI lane lands. Goes through `build_agent()` from `src.core.bootstrap`
so the same factory the GUI consumes is exercised — the CLI doubles as a
contract-conformance probe for `docs/integration_contract_zh.md`.

Run with:
    python -m src.cli                  # online (DeepSeek + full tool set)
    python -m src.cli --offline        # EchoLLMProvider + offline tool subset
    python -m src.cli --show-reasoning # dump assistant reasoning_content per turn
"""

from __future__ import annotations

import argparse
import json
import sys
from textwrap import shorten
from typing import Any

from .core import AgentEvent, build_agent

_HELP = """Commands:
  /help          show this help
  /reset         clear conversation history (rebuild agent)
  /quit, /exit   leave the REPL  (also: Ctrl-D / Ctrl-C)
Otherwise: type your message and press Enter."""

_RESULT_WIDTH = 400


def _format_tool_call(payload: dict[str, Any]) -> str:
    args = payload.get("arguments") or {}
    try:
        args_str = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        args_str = str(args)
    return f"  -> tool: {payload['name']}({args_str})"


def _format_tool_result(payload: dict[str, Any]) -> str:
    result = payload["result"]
    if getattr(result, "success", True):
        body = str(getattr(result, "data", result))
    else:
        body = f"ERROR: {result.error}"
    return f"  <- result: {shorten(body, width=_RESULT_WIDTH, placeholder='...')}"


def _print_event(event: AgentEvent) -> str | None:
    if event.kind == "tool_call":
        print(_format_tool_call(event.payload))
    elif event.kind == "tool_result":
        print(_format_tool_result(event.payload))
    elif event.kind == "final":
        return event.payload.get("text") or "(empty reply)"
    return None


def _dump_reasoning(agent: Any, watermark: int) -> None:
    snapshot = agent.conversation.snapshot()
    for msg in snapshot[watermark:]:
        if msg.role == "assistant" and msg.reasoning_content:
            print("  --- reasoning ---")
            print(msg.reasoning_content)
            print("  --- end reasoning ---")


def run_repl(*, offline: bool, show_reasoning: bool) -> int:
    try:
        agent = build_agent(offline=offline)
    except FileNotFoundError as exc:
        print(f"build_agent failed: {exc}", file=sys.stderr)
        print("hint: pass --offline to skip the DeepSeek key requirement.", file=sys.stderr)
        return 2

    mode = "offline" if offline else "online"
    print(f"PKU Captain CLI — {mode} mode. Type /help for commands, /quit to exit.")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in {"/quit", "/exit"}:
            return 0
        if line == "/help":
            print(_HELP)
            continue
        if line == "/reset":
            agent = build_agent(offline=offline)
            print("(conversation reset)")
            continue

        watermark = len(agent.conversation)
        final_text: str | None = None
        try:
            for event in agent.turn(line):
                printed = _print_event(event)
                if printed is not None:
                    final_text = printed
        except KeyboardInterrupt:
            print("\n(turn interrupted)")
            continue
        except Exception as exc:  # noqa: BLE001 — CLI: surface, keep session alive
            print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        if final_text is not None:
            print(final_text)
        if show_reasoning:
            _dump_reasoning(agent, watermark)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Interactive REPL for the PKU Captain agent.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use EchoLLMProvider + offline tool subset (no API key needed).",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Dump assistant reasoning_content after each turn.",
    )
    args = parser.parse_args(argv)
    return run_repl(offline=args.offline, show_reasoning=args.show_reasoning)


if __name__ == "__main__":
    sys.exit(main())
