# Task 008 — `KimiProvider` (vision LLM, **optional**)

> Delegated to a worktree Claude. Before starting, read `CLAUDE.md` and `docs/integration_contract_zh.md`.
>
> **Optional task**: `KimiProvider` is item #1 on the cut-list in `docs/roadmap_zh.md`. Delegate it only if the rest of Wave A is progressing well and the 06-01 milestone has slack; otherwise skip it — DeepSeek alone is enough to carry the demo.

## Goal

Implement `KimiProvider` — an `LLMProvider` subclass for Kimi, serving as the vision LLM channel (per the committed stack: DeepSeek for chat, Kimi for vision).

## Background

The `LLMProvider` abstract base class is in `src/llm/base.py`: implement `chat(messages, tools=None) -> ChatResponse`. The closest reference implementation is `src/llm/deepseek.py` (`DeepSeekProvider`) — it shows API-key injection, message-format conversion, and tool-call passthrough. Note the base class's `ChatMessage` / `ChatResponse` carry a `reasoning_content` field — that is specific to DeepSeek's thinking mode; Kimi does not need it, leave it `None`.

## Deliverables

- New file `src/llm/kimi.py` — `KimiProvider(LLMProvider)`.
- Edit `src/llm/__init__.py` — export `KimiProvider`.
- **No `bootstrap.py` change needed**: there is no vision call site yet, so `build_agent()` still uses DeepSeek. This task only delivers the subclass — independently instantiable and registrable into an `LLMProviderRegistry`.

## Implementation requirements

- Mirror `DeepSeekProvider`'s structure: the constructor takes an `api_key`; `chat()` converts a `list[ChatMessage]` into a Kimi API request and parses the response back into a `ChatResponse`.
- Support image input — that is Kimi's reason for existing in this project. If a message in `chat()` contains image content, send it in Kimi's multimodal format.
- Wrap API errors in a clear exception type (see `DeepSeekAPIError`); do not silently swallow them.
- API key: by convention, place it at `secrets/kimi_key.txt` (`secrets/` is already gitignored). A worktree has no `secrets/`, so **online self-testing is not possible — this is expected**; use offline checks instead (see Acceptance).
- Subclass pattern; modules side-effect-free on import.
- Under an "Implementation notes" section in this file, record Kimi's base URL, model name, and multimodal message format, to help the captain wire a vision call site during integration.

## Dependencies

Independent task.

## Acceptance

- [ ] `find src -name '*.py' -print0 | xargs -0 python -m py_compile` passes.
- [ ] `ruff check src` passes.
- [ ] `from src.llm import KimiProvider` succeeds; an instance can be constructed with a fake key (construction must not trigger a network call).
- [ ] `KimiProvider` can be `register()`ed into an `LLMProviderRegistry` (`src/llm/base.py`).
- [ ] `python -m src.cli --offline` still starts.

## Commit and boundaries

- Commit to **this worktree branch** using Conventional Commits.
- **Do not** push, **do not** merge into main, **do not** open a PR — the captain integrates (see `000_delegation_guide.md`).
- **Do not** tick `docs/roadmap_zh.md`.
- Ensure all changes are committed before finishing.
