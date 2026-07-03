# Code structure

How modules, classes, and their boundaries should be shaped.

## Subclass + register, never ad-hoc dispatch

New tools, workflows, LLM providers, and sources are subclasses of the ABCs in `src/{tools,workflows,llm}/base.py` and `src/rag/source.py`, registered against the matching `*Registry` **at the call site** (`src/core/bootstrap.py`), not by import side-effect. This is the course's OOP rubric showcase — reach for a subclass before a branch.

- **Prefer**: a new `Tool` subclass + one `registry.register(...)` line in bootstrap.
- **Avoid**: auto-registration at import; a growing `if name == ...` ladder a polymorphic call would replace.

## Keep modules side-effect-free at import

Importing a module must not register anything, hit the network, or spawn a subprocess. Registration is explicit in `bootstrap._build_tools()`; network tools register **online-only** there. This keeps `--offline` honest and imports cheap.

## Deep modules, simple seams

Favour a small interface over a large one for a given amount of functionality (Ousterhout's "deep module": maximize behavior hidden behind a narrow interface). The clearest seam here is `src.core.build_agent` — GUI code constructs an `Agent` only through that factory and never imports a concrete `LLMProvider`/`Tool`. When adding a capability, widen behavior behind the existing seam before adding a new public entry point.

## Break import cycles with lazy re-exports, not layering hacks

`src/core/__init__.py` re-exports `build_agent`/`build_source_registry` lazily via PEP 562 `__getattr__` because `bootstrap` imports tools and some tools import `src.core.memory` — an eager re-export reintroduces a `core`↔`tools` cycle. When two packages genuinely need each other, defer the import to call time rather than reshuffling ownership.

## One offline reference subclass per hierarchy

Each hierarchy ships exactly one dependency-free reference implementation — `EchoLLMProvider`, `ClockTool`, `StaticSource`, `HelloWorkflow` — so the loop and tests run with no API keys or live endpoints. When you add a hierarchy, add its one offline reference; leave the rest for teammates.

See also: `ARCHITECTURE.html` (the actual map), `docs/integration_contract_zh.md` (the GUI↔backend seam).
