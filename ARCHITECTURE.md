# ARCHITECTURE.md

The **structural map** of PKU Captain — the box-and-arrow view of what talks to what and where the boundaries are. Maintained by the `architecture` skill on structural changes only.

**What this file is / isn't.** This is *shape*: components, boundaries, the seam, runtime data flows, external dependencies. It is **not** the rules — those invariants ("keep the memory store shared", "don't revert accumulation to replace") live in `CLAUDE.md` "Repo status". It is **not** the seam contract — that binding API surface is `docs/integration_contract_zh.md`. When this file and CLAUDE.md would say the same thing, this file links rather than restates.

---

## 1. The two lanes and the seam

PKU Captain is a PyQt6 desktop app split into a **GUI lane** and a **backend lane**, joined by a single factory seam. The GUI never constructs concrete providers/tools/sources — it calls factories in `src/core/bootstrap.py` and talks to the backend only through the abstractions those factories return.

```
            ┌──────────────────────────── GUI lane (src/ui/) ────────────────────────────┐
            │  MainWindow ── DashboardPanel ── ChatPanel ── dialogs (treehole/P-Lib/      │
            │       │            │                │          dean/memory/文档库/calendar)  │
            │       │   QThreads: AgentWorker · DashboardWorker · WorkflowWorker          │
            │       │   QThreadPool: tool_call_worker.run_async (dialog blocking calls)   │
            └───────┼────────────┼────────────────┼───────────────────────────────────────┘
                    │            │                │
        ┌───────────▼────────────▼────────────────▼───────────┐
        │  SEAM — src/core/bootstrap.py  (lazy re-export via   │   ← docs/integration_contract_zh.md
        │  src/core/__init__.py PEP 562 __getattr__)           │
        │  build_agent · build_source_registry ·               │
        │  build_session_store · build_session_titler ·        │
        │  build_dashboard_cache · build_doc_reader ·          │
        │  build_chat_llm · available_chat_models ·            │
        │  apply_chat_model · reset/restore_conversation       │
        └───────────┬──────────────────────────────────────────┘
                    │ returns Agent / SourceRegistry / stores (abstractions only)
   ┌────────────────▼──────────────────── Backend lane ───────────────────────────────────┐
   │  core/   Agent (kernel + turn loop) · Conversation · MemoryStore · MemoryLearnService │
   │          · SessionStore · SessionTitler · DashboardCache · VisionRouter               │
   │  llm/    LLMProvider(ABC) → DeepSeekProvider · KimiProvider · EchoLLMProvider         │
   │  tools/  Tool(ABC)+ToolRegistry → clock · memory · doc_base · pku3b* · plib · dean*   │
   │          · treehole* · calendar_reminder                                              │
   │  workflows/ Workflow(ABC)+WorkflowRegistry → MorningBriefing · Hello (+WorkflowTool)  │
   │  rag/    Source(ABC)+SourceRegistry → DeanSource · CalendarSource (Embedder/KB retired)│
   └───────────┬──────────────────────────────────────────────────────────────────────────┘
               │ subprocess / HTTPS
   ┌───────────▼───────────────── External processes & APIs ──────────────────────────────┐
   │  pku3b (Rust CLI, our fork) · plib-cli · pku-dean-cli · pku-treehole-cli (sibling     │
   │  venvs) · DeepSeek API · Kimi/Moonshot API · pdftoppm (doc render) ·                  │
   │  osascript + launchctl (macOS Calendar reminders / treehole notifier)                 │
   └───────────────────────────────────────────────────────────────────────────────────────┘
```

**Entry points.** `python -m src` (`src/__main__.py` → `ui.main_window`, defaults offline); `python -m src --online`; `python -m src.cli` (REPL on the same `build_agent` loop — the GUI-seam conformance probe); `scripts/smoke_deepseek.py` (real DeepSeek round-trip).

---

## 2. The four OOP hierarchies (the course rubric)

Every extension is a **subclass + register against a `*Registry`** — no ad-hoc dispatch. Modules stay side-effect-free; registration happens at the call site (`bootstrap.py`).

| Hierarchy | Base (`src/.../base.py`) | Registry | Reference offline subclass | Real subclasses |
|---|---|---|---|---|
| Tool | `tools/base.py` `Tool` / `ToolResult` | `ToolRegistry` | `ClockTool` | memory, doc_base search/read, pku3b assignments/announcements/coursetable, plib, dean resources/updates, treehole, calendar_reminder |
| Workflow | `workflows/base.py` `Workflow` | `WorkflowRegistry` | `HelloWorkflow` (`agent_callable=False`) | `MorningBriefingWorkflow` |
| LLM | `llm/base.py` `LLMProvider` | (none — factory-selected) | `EchoLLMProvider` | `DeepSeekProvider`, `KimiProvider` |
| Source | `rag/source.py` `Source` | `SourceRegistry` | `StaticSource` | `DeanSource`, `CalendarSource` |

`LLMProvider` has no registry: the chat brain is **switchable at runtime** (DeepSeek ⇄ Kimi) via `build_chat_llm` / `apply_chat_model`. A switch resets the conversation (single-model history) and gates `doc_read` on vision capability.

---

## 3. Runtime data flows

**Chat turn** — `ChatPanel` → `AgentWorker` (QThread) → `Agent.turn()`:
```
user msg → Conversation.add_user → loop (≤8 iters):
   _messages_for_llm()  [snapshot + memory folded into the leading system msg, per-iteration]
   → llm.stream_chat → events: reasoning_delta · assistant_delta · llm_response
   → if tool_calls: tool_call → tool.invoke → tool_result (per call)
       └ ToolResult.images? → injected as one multimodal user msg AFTER all results (Kimi reads pages)
   → context_usage → (no tool_calls) → final
→ MainWindow._on_agent_event dispatches each event to ChatPanel
```
Memory is folded per-iteration into a *snapshot copy* only — never written into `Conversation`. One bubble per assistant segment (finalized on each `tool_call`).

**Dashboard refresh** — `DashboardPanel` → `DashboardWorker` (QThread) → `ThreadPoolExecutor` fan-out over selected tool keys → `as_completed` emits `item_result`/`item_error` per card (error-isolated). `DashboardCache` (`data/dashboard_cache/<key>.json`, raw payloads) seeds paint at startup; a silent refresh repaints only cards whose `_signature` changed. Scoped refresh: per-card buttons emit `partial_refresh_requested([key])`, header 刷新 reloads all.

**Dialog actions** — dashboard dialogs get tools from the injected `ToolRegistry` (`tools.find(name)`), gate online-only entries on membership, and run every blocking call through `tool_call_worker.run_async` onto a `QThreadPool`.

**Workflows** — GUI button path: `WorkflowWorker` (QThread) → `workflow.run`. Agent path: each `agent_callable` workflow is wrapped in a `WorkflowTool` registered into the `ToolRegistry`, so the model starts it through the normal tool-call loop.

**Session persistence** — `SessionStore` writes `data/sessions/<id>.json` per turn-finish/close (after the first real turn); `SessionTitler` (deepseek-v4-flash, non-think) names it async; `restore_conversation` reloads, re-seeding today's system prompt and dropping incomplete tool-call tails.

---

## 4. External dependencies

| Dependency | Used by | Transport | Notes |
|---|---|---|---|
| `pku3b` (Rust CLI, fork) | `tools/pku3b.py` + pku3b_* tools | subprocess (`--format json`) | PATH then `.local/cargo/bin/pku3b` fallback; stdout breaks on `>` redirect |
| `plib-cli` (fork) | `PLibMaterialsTool` | subprocess, `../plib-cli/.venv` | auto-injects `PLIB_EMAIL`/`PLIB_PASSWORD` from `secrets/plib/` |
| `pku-dean-cli` | `DeanResourcesTool` / `DeanUpdatesTool` | subprocess, `../pku-dean-cli/.venv` | public, no creds |
| `pku-treehole-cli` | `treehole_updates.py` | subprocess, `../pku-treehole-cli/.venv` | IAAA creds from `secrets/treehole/`; macOS notifier via `launchctl` |
| DeepSeek API | `DeepSeekProvider` | HTTPS SSE | `deepseek-v4-pro`, `reasoning_effort=max`, thinking replay required |
| Kimi/Moonshot API | `KimiProvider` | HTTPS SSE | `kimi-k2.6`, vision (doc_read page images) |
| `pdftoppm` | `doc_base.py` doc_read | subprocess | renders PDF pages to images |
| `osascript` | `CalendarReminderTool` | subprocess (macOS) | writes Calendar.app events |

**Data layout.** `secrets/` (gitignored — API keys, P-Lib/treehole creds, sessions), `data/` (gitignored — memory, sessions, inboxes, caches), `doc_base/` (committed — split PDFs + `manifest.json`), `downloads/` (gitignored).

---

## 5. Cross-references

- Invariants & "don't break this" rules → `CLAUDE.md` "Repo status".
- The binding GUI↔backend API/threading/event/error contract → `docs/integration_contract_zh.md`.
- Why decisions were made → `DEVCHANGELOG.md`.
- How to confirm behavior by hand → `VERIFICATION.md`.
