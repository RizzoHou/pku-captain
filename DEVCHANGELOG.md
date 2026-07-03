# DEVCHANGELOG.md

The **development decision log** — why changes were made, not what shipped. Maintained by the `devchangelog` skill, append-only, newest first.

**Boundary.** `CHANGELOG.md` records *what shipped* (user-facing, per merge). This file records *why + what the agent did* (decisions, tradeoffs, actions) for the human auditor. A decision ("chose X over Y because Z") goes here; a feature line ("added the calendar button") goes in CHANGELOG. The same change can produce one entry in each on different axes.

---

## 2026-07-03 — Reimplement used pku3b subset as pure-Python `pypku3b`, drive in-process, drop the Rust binary

- **What**: built `pypku3b` (new standalone repo `~/projects/pypku3b`, GitHub `RizzoHou/pypku3b`) reimplementing the four pku3b surfaces the app uses (assignments/announcements/coursetable/identity) over `requests`+`bs4`, vendored it under `vendor/pypku3b` via `git subtree` (fifth hatchling `packages` entry), and rewrote the three pku3b Tools + `bootstrap._sync_pku3b_identity_memory` to drive `pypku3b.Client` in-process via an injectable `client_factory`. Removed the subprocess wrapper, `pku3b_links.py`, `AnnouncementDateCache`, and the Rust install. Captain is now fully standalone.
- **Decision**: **Strategy B (in-process library), not a drop-in CLI binary** — the user asked to follow "the way other CLI tools get integrated" (dean/plib/treehole are driven in-process), and "fully standalone" means removing the subprocess, not swapping the binary. Ships a CLI too, but only for standalone use + golden diffing.
- **Decision**: **credentials from `secrets/pku/{id,password}` (plaintext), not pku3b's AES `cfg.toml`** — drops a `cryptography` dep and matches the plib/treehole secrets convention; the host app owns its secrets dir.
- **Decision**: **`id` = blake2b(course_id\0content_id)[:16 hex], not Rust's SipHash-1-3** — nothing downstream re-derives ids against pku3b (detail-by-id filters a fresh list), so ids only need to be stable + self-consistent; reproducing Rust's `str`-framed SipHash was a real cost for zero benefit (one-time re-warm of the orphaned date cache is harmless).
- **Decision**: **TLS pinned to the OS trust store, not certifi** — `course.pku.edu.cn`'s GlobalSign chain verified against the system store (curl/openssl OK) but not certifi on this box; pku3b works because native-tls uses the OS store, so `default_ca_bundle()` prefers `SSL_CERT_FILE`/OpenSSL default and falls back to certifi. Found by live-testing (identity/coursetable via portal/iaaa passed, Blackboard failed).
- **Decision**: **announcement dates come inline, killing the `announcement show` per-id subprocess + `AnnouncementDateCache`** — the course-page scrape already carries 发布时间 (nested in a `<div>`, not a direct `<p>` as pku3b's narrower check assumed; matched on text not tag). 50/106 dated matches pku3b's own ~half coverage (the undated rows are the body-snippet fallback entries pku3b also emits — confirmed against golden).
- **Decision**: **keep ToolResult `data` shapes byte-identical** so the GUI/dashboard/formatters/agent seam is untouched; assignment `url`/`submit_url`/`blackboard_content_id` rebuilt from live crawl data (`Assignment.content_id` + course-menu URL) since the old `Pku3bLinkResolver` probed pku3b's now-never-written binary cache.
- **Files**: `pypku3b` repo (`src/pypku3b/{client,blackboard,portal,iaaa,http,cache,dates,ids,models,config,errors,cli}.py` + tests); `vendor/pypku3b` (subtree); `src/tools/pku3b.py` (subprocess→in-process backend), `src/tools/pku3b_{assignments,announcements,coursetable}.py`, `src/core/bootstrap.py`, `pyproject.toml`, `conftest.py` (worktree import bridge); removed `src/tools/pku3b_links.py` + `tests/test_pku3b_{links,announcements_dates}.py`; added `tests/test_pku3b_tools.py`.
- **Verify**: see VERIFICATION.md "pypku3b in-process migration". Golden-diffed live (identity exact, assignments 22/22 all fields, coursetable structural, announcements dated-coverage) + fresh cold-login through the real Tools; 380 pytest + smoke green.

## 2026-07-03 — Universal 账号中心 + configurable model endpoints (CredentialStore)

- **What**: consolidated the three scattered credential entry points into one tabbed `LoginDialog` (统一身份/树洞 · P-Lib · 模型配置) behind a dashboard 账号 button; added `CredentialStore` as the single `secrets/` writer/status/clear; reframed the chat brains as two configurable roles (`text`/文本模型 default DeepSeek, `visual`/视觉模型 default Kimi) reading endpoint/model/key from `secrets/models.json`; fixed P-Lib login to actually persist creds.
- **Decision**: **new `CredentialStore` in `core/` (writes) but leave tool reads untouched** — the vendored plib/treehole libs already resolve their own creds from disk, so a full read-side refactor is churn with no payoff; the store owns the *canonical paths + writes + status*, mirroring what tools read. Small blast radius, on-theme for the OOP rubric.
- **Decision**: **model roles = editable endpoint/model over the *existing* provider impls, not a generic provider** — `text` stays a `DeepSeekProvider` (thinking wire format), `visual` a `KimiProvider` (vision); only `base_url`/`model`/`api_key` become user-configurable. Pointing a role at a wire-incompatible vendor is out of scope (that's a new provider subclass). Keeps the DeepSeek reasoning-replay / Kimi thinking semantics intact while satisfying "custom endpoints, DeepSeek/Kimi as defaults".
- **Decision**: **role keys renamed `deepseek`/`kimi` → `text`/`visual`** across bootstrap + main_window (BREAKING seam value); provider `.name` stays `deepseek`/`kimi` (implementation identity). Legacy `secrets/api_keys/*_key.txt` kept as api_key fallback so existing checkouts need no migration.
- **Decision**: **login page not gated on online mode; model changes apply on next launch** — a fresh offline user configures keys/endpoints + P-Lib, restarts online (treehole SMS + P-Lib live validation still need network). Rebuilding the live agent + 3 QThreads mid-session to flip offline→online was too risky for this pass; "prompt, don't force" surfaces via the offline startup diagnostic.
- **Decision**: retain in-flight `run_async` handles in a **list**, not a single `self._pending` slot — a second call was GC'ing the first's `_AsyncSignals` mid-task → "wrapped C/C++ object deleted" abort (the dialog fires status-check then login back-to-back).
- **Files**: `src/core/credentials.py` (new), `src/ui/login_dialog.py` (new), `src/core/{__init__,bootstrap}.py`, `src/ui/{dashboard,main_window,chat_panel}.py`, `tests/test_{credentials,login_dialog,bootstrap_docbase,dashboard_dialogs,dashboard_gating}.py`, `docs/setup_zh.md`, `CHANGELOG.md`, `ARCHITECTURE.html`.
- **Verify**: VERIFICATION.md → "Universal 账号中心 + model endpoints" (396 pytest green; real DeepSeek round-trip through the new `build_agent`; legacy-key fallback confirmed; headless account-dialog open offline).

## 2026-07-03 — ARCHITECTURE.md → self-contained ARCHITECTURE.html

- **What**: replaced `ARCHITECTURE.md` with a single self-contained `ARCHITECTURE.html` (inline CSS, no external assets) — layered CSS diagram for the two-lanes-and-seam view, styled tables, PKU-red theme mirroring `src/ui/styles.py`, `prefers-color-scheme` dark variant. Content is a faithful 1:1 port; only the format changed. Updated the `architecture` skill to maintain HTML and repointed every live cross-reference (CLAUDE.md ×5, `devchangelog`/`tastes` skills, `TASTES/{README,code-structure,process}`); left historical `DEVCHANGELOG`/`VERIFICATION` mentions of the old `.md` name intact.
- **Decision**: chose HTML over Markdown for the richer rendered view the captain asked for, accepting the tradeoff that GitHub renders `.md` natively but shows `.html` as raw source — the visual payoff lands only in a local browser / GitHub Pages, not the repo file view.
- **Decision**: kept it **one self-contained file** (inline `<style>`, no JS/CDN/fonts) so it opens from `file://` with no build step, matching the app's offline-first posture; the skill now enforces "reuse existing classes, escape `<`/`>`/`&`, stay valid HTML, visual-audit the render."
- **Files**: `ARCHITECTURE.html` (new), `ARCHITECTURE.md` (removed), `.claude/skills/architecture/SKILL.md`, `.claude/skills/{devchangelog,tastes}/SKILL.md`, `CLAUDE.md`, `TASTES/{README,code-structure,process}.md`.
- **Verify**: rendered both light + dark mode via headless Chromium and visually audited (fixed a low-contrast code chip in the red table header); n/a for VERIFICATION.md (doc-format change, not app behavior).

## 2026-07-01 — Vendor plib/dean/treehole in-process (git subtree), drop subprocess transport

- **What**: pulled the three self-crafted Python CLIs into `vendor/` via `git subtree`, exposed them as top-level packages (`plib_cli`/`dean`/`treehole`) through the pyproject hatchling `packages` mapping, and rewired the `plib`/`dean*`/`treehole*` Tool wrappers to drive the libraries **in-process** instead of shelling out to sibling `.venv`s / a `sys.path` shim. `pku3b` (Rust) left untouched.
- **Decision**: **scope = Python CLIs only** (captain's call, post-deadline personal project). pku3b is a separate, much larger effort — reimplementing its ~7.8k-LOC Blackboard scraper in Python is the real "standalone" blocker; the three Python siblings (~700–860 core LOC each, `requests`+`bs4`) are a cheap lift-and-shift with clean library seams already present.
- **Decision**: **git subtree over submodule/PyPI** (captain's call) — a submodule reintroduces a `clone --recursive` external step (fights "standalone"); subtree vendors the code into the repo, one `pip install -e .` provides everything, `subtree pull --squash` still tracks upstream.
- **Decision**: keep the **Tool subclasses + schemas + `{ok,data}` envelope byte-identical** — only the transport under them changed. Reused each library's own serialization (`dean.output.jsonable`, model `.to_dict()`) so `data` shapes don't drift; injectable `client_factory` replaces subprocess mocking in tests.
- **Decision**: plib creds now passed as explicit `Credentials(...)` (was `PLIB_EMAIL`/`PLIB_PASSWORD` env into the subprocess); redaction preserved. Treehole macOS notifier daemon now runs pku-captain's **own** venv `treehole` console script (new `[project.scripts]`) instead of the sibling venv binary.
- **Files**: `vendor/{plib-cli,pku-dean-cli,pku-treehole-cli}/` (subtree), `pyproject.toml`, `src/tools/{dean_resources,dean_updates,plib_materials,treehole_updates}.py`, `tests/test_{dean_tool,dean_updates_tool,plib_materials_tool,redact}.py`, `docs/setup_zh.md`.
- **Verify**: VERIFICATION.md → "Vendored plib/dean/treehole in-process" (pytest 376 green; live dean sidebar round-trip; treehole macOS notifier re-install).

## 2026-07-01 — TASTES/ coding-taste directory + tastes skill

- **What**: added `TASTES/` (README + four broad topic files: `code-structure`, `naming-and-style`, `correctness`, `process`) capturing prescriptive coding-taste guidance, plus a `tastes` project skill to maintain it.
- **Decision**: seed **codebase-first** — rules are distilled from this repo's own lessons (subclass+register, side-effect-free imports, accumulate-don't-replace, raw-byte CJK decode) with external principles (Ousterhout deep modules, Torvalds eliminate-special-cases) as a thin supplement only; generic internet boilerplate (SOLID/DRY lectures) explicitly excluded. Project-specific tastes are higher-value than generic ones and stay true to the code.
- **Decision**: **a few broad files, not many narrow ones** (captain's call) — four topics keep the surface scannable and maintenance low.
- **Decision**: TASTES sits on a distinct *taste* axis — cross-references CLAUDE.md (live invariants) / DEVCHANGELOG (dated decisions) / ARCHITECTURE (structure), never restates them; the skill enforces that boundary plus a drift audit against CLAUDE.md.
- **Decision**: docs/tooling, not user-facing → DEVCHANGELOG entry only, **no CHANGELOG** (mirrors the agentic-auditing-machinery precedent); not a code structural change, so ARCHITECTURE/VERIFICATION don't fire.
- **Files**: `TASTES/{README,code-structure,naming-and-style,correctness,process}.md`, `.claude/skills/tastes/SKILL.md`.
- **Verify**: n/a (prose artifacts; no runtime behavior).

## 2026-06-29 — Credential redaction at the tool boundary + CLAUDE.md prune

- **What**: added `src/tools/redact.py` (`redact(text, secrets)`); `run_plib` and `TreeholeAuthService` now strip injected/held credentials from any error string before it becomes a `ToolResult.error`. Compressed three verbose CLAUDE.md paragraphs to bring the file back under the 39k budget (38,561, below the 38,879 baseline).
- **Decision**: redact at the **tool/subprocess boundary**, not centrally in `Agent.turn()` — keeps `core` free of secret-path knowledge and strips exactly what each tool injects/holds. pku3b is **not** covered: its portal password lives in pku3b's own `cfg.toml` and never enters our process, so there is no value to strip (documented in `redact.py`, not faked).
- **Decision**: fail safe — `redact` over-redacts a short secret rather than risk under-redacting, and skips empty/whitespace secrets (an empty `str.replace` would shred the text).
- **Decision**: the CLAUDE.md prune **compresses in place**, it does not relocate the macOS gotchas to ARCHITECTURE.md — gotchas are *rules* and must keep firing in CLAUDE.md; relocating them would break the structure-vs-rules boundary. Only step-by-step elaboration was cut; every load-bearing rule kept.
- **Files**: `src/tools/{redact,plib_materials,treehole_updates}.py`, `tests/test_redact.py`, `CLAUDE.md`.
- **Verify**: VERIFICATION.md → "Credential pre-release audit" (fix applied; `pytest tests/test_redact.py`).

## 2026-06-29 — Agentic auditing machinery (DEVCHANGELOG / ARCHITECTURE / VERIFICATION + skills)

- **What**: added three repo-root audit artifacts and three project-level skills to maintain them; wired a plan-gate convention into CLAUDE.md.
- **Decision**: relocate the human's verification off the code (needs stack knowledge) onto stack-agnostic artifacts (handoff doc `docs/external/...`). Three skills, not one combined — single-responsibility matches the repo's subclass-and-register aesthetic — but each fires by **change type** (devchangelog ~every change, architecture only on structural change, verification on user-visible/release-critical change), not all-every-task, to avoid four mandatory post-task rituals alongside `claude-md-improver`.
- **Decision**: keep DEVCHANGELOG separate from CHANGELOG on a why-vs-what axis; keep ARCHITECTURE separate from CLAUDE.md on a structure-vs-rules axis. Cross-reference, never restate.
- **Decision**: track `.claude/skills/` (un-ignored just that subtree; repo is PRIVATE) so the machinery is durable team/worktree state, consistent with how `CLAUDE.md` is tracked. Rest of `.claude/` stays gitignored.
- **Decision**: plan-gate stays a CLAUDE.md convention, not a fourth skill (user capped skills at three; machinery is experimental, to be packaged as a Claude plugin once mature).
- **Files**: `.claude/skills/{devchangelog,architecture,verification}/SKILL.md`, `ARCHITECTURE.md`, `DEVCHANGELOG.md`, `VERIFICATION.md`, `.gitignore`, `CLAUDE.md`.
- **Verify**: VERIFICATION.md → "Agentic auditing machinery" + "Credential pre-release audit".
