# VERIFICATION.md

Human-executable verification steps. Maintained by the `verification` skill. The architect (Rizzo) runs these to confirm a change is *real*, not just plausible — verification relocated off the code and onto observable behavior. "Looks plausible" is the danger zone, not the safe zone.

**How to use.** Work the **Pending** queue top-down: run each step, check the observed result against the expected one. When satisfied, move the entry to **Verified** (or tell the agent to collapse it). Steps marked `[agent- run]` were already run by the agent; the rest are yours.

---

## Pending verification

### 2026-07-03 — pku3b reimplemented as in-process `pypku3b` (no external binary)

**Proves**: the captain reads 作业/公告/课表/身份 from PKU 教学网 + 门户 entirely in-process via the vendored `pypku3b`, with **no `pku3b` Rust binary** and no behavior change to the dashboard/agent — driven from `secrets/pku/{id,password}`.

**Steps**:
1. `[agent-run]` `pytest tests/` → **380 passed, 2 skipped** (rewritten `test_pku3b_identity_memory.py` + new `test_pku3b_tools.py` drive the `client_factory` seam).
2. `[agent-run]` `python scripts/smoke_deepseek.py` → **smoke test passed** (agent kernel + wire format unaffected by the transport swap).
3. `[agent-run]` Fresh-install check: in the **main** checkout `pip install -e . -q && python -c "import pypku3b; print(pypku3b.__version__)"` → expect `0.1.0` (fifth hatchling `packages` entry exposes it top-level). (Do this in main, not a worktree — worktrees must not `pip install` into the shared venv.)
4. `[agent-run]` Live end-to-end through the real Tools (needs `secrets/pku/`), fresh cold login (`rm -f secrets/pku/cookies.json data/pku3b_cache/*`): assignments → **success, N records with `deadline_iso`/`submit_url`/`blackboard_content_id`**; coursetable → **success, N blocks**; announcements → **~half carry `posted_date` + `url`**; identity sync sets `identity.name`/`identity.student_id`. (Confirmed: identity matched golden pku3b exactly, assignments 22/22 all fields, announcements 50/106 dated.)
5. **No binary needed**: `which pku3b || echo "no pku3b binary"` and still run step 4 — expect it works without any `pku3b`/`cargo` on PATH.
6. **GUI (online, needs `secrets/pku/`)**: `python -m src --online`, watch the dashboard 近期 DDL / 课程通知 / 课表 cards populate; click a 作业 row → opens the Blackboard submit page in the browser; click a 课程通知 row → opens the 通知 page. Expect identical behavior to the pre-migration binary path.
7. **OTP path**: if the account requires a phone token, the 课表 card shows the Chinese hint `课表接口需要手机令牌 OTP，请在仪表盘顶部输入 OTP 后刷新。`; enter an OTP at the dashboard top and refresh → table loads.
8. **No-credentials / offline negative**: with `secrets/pku/` absent, `python -m src --online` still opens (identity sync silently skips); a pku3b card refresh shows a Chinese error, not a crash.

**Automated**: `pytest tests/test_pku3b_tools.py tests/test_pku3b_identity_memory.py` (output shapes, client_factory seam, credential redaction, OTP hint, sync-once/skip-without-creds); plus `pypku3b`'s own suite in `~/projects/pypku3b` (`pytest` for parsers/dates/ids/cache; `PYPKU3B_LIVE=1 pytest tests/live` for the network round-trip).

---

### 2026-07-01 — Vendored plib/dean/treehole in-process (no subprocess)

**Proves**: the three self-crafted CLIs now run in-process from `vendor/` (via `git subtree`) with **no behavior change** — one `pip install -e .` provides everything, no sibling `.venv`s, and search/dean/treehole still work. Also that the macOS treehole notifier daemon uses pku-captain's own venv binary.

**Steps**:
1. `[agent-run]` `pytest tests/` → **376 passed, 2 skipped** (the rewritten dean/plib/redact suites drive the in-process seam).
2. `[agent-run]` Fresh-install check: `.venv/bin/pip install -e . -q && .venv/bin/python -c "import plib_cli, dean, treehole; print('ok')"` → expect `ok` (hatchling `packages` mapping exposes the vendored libs top-level).
3. `[agent-run]` Live public round-trip (no creds): `.venv/bin/python -c "from src.tools.dean_resources import DeanResourcesTool; print(len(DeanResourcesTool().invoke({'action':'sidebar'}).data))"` → expect a number ~50 (real fetch from dean.pku.edu.cn, in-process). Network-down → prints an error, no crash.
4. **P-Lib (online, needs `secrets/plib/`)**: `python -m src --online`, ask "P-Lib 今天还能下载几次？" → expect a quota number, same as before the migration. Or CLI: `.venv/bin/python -c "from src.tools.plib_materials import PLibMaterialsTool; print(PLibMaterialsTool().invoke({'action':'quota'}).data)"`.
5. **Treehole (online, needs login)**: in the GUI, open 树洞 → confirm followed-hole updates still load (in-process `import treehole`, no sibling checkout present).
6. **macOS notifier only**: after `pip install -e .`, `ls .venv/bin/treehole` → expect it exists (new `[project.scripts]` entry). In 树洞 → 消息通知 → 开启通知, then `launchctl print gui/$(id -u)/com.pku.captain.treehole.notify | grep program` → expect the path points at `<repo>/.venv/bin/treehole`, not `../pku-treehole-cli/.venv`. (macOS-only; inert elsewhere.)

**Automated**: `pytest tests/test_dean_tool.py tests/test_dean_updates_tool.py tests/test_plib_materials_tool.py tests/test_redact.py` (in-process dispatch, data-shape passthrough, download timeout, credential redaction).

---

### 2026-06-29 — Agentic auditing machinery

**Proves**: the three audit files + three skills exist, are wired, and `.claude/skills/` is tracked (so they reach teammates/worktrees) while the rest of `.claude/` stays private.

**Steps**:
1. `ls .claude/skills` → expect `architecture  devchangelog  verification`.
2. `git check-ignore .claude/skills/devchangelog/SKILL.md` → expect **no output** (skills are tracked). `git check-ignore .claude/settings.local.json` → expect it **is** ignored (prints the path).
3. `git status --porcelain` → expect `ARCHITECTURE.md`, `DEVCHANGELOG.md`, `VERIFICATION.md`, `.claude/skills/...`, modified `.gitignore` + `CLAUDE.md` staged/untracked — and **not** `.claude/worktrees/` or `settings.local.json`.
4. In a Claude Code session here, confirm the three skills appear in the skill list (descriptions mention DEVCHANGELOG / ARCHITECTURE / VERIFICATION).

**Automated**: none (docs/skills, no code path).

---

### 2026-06-29 — Credential pre-release audit

**Proves**: no credential (P-Lib/treehole/IAAA password, API key, session token) reaches an LLM request context, a log, or a persisted conversation/cache file.

**Findings (the report — read this part).**

*Safe, confirmed:*
- API keys (DeepSeek, Kimi) are read from `secrets/api_keys/*` and sent **only** in the `Authorization: Bearer` header (`deepseek.py:97`, `kimi.py:109`); never in a request body, conversation, or disk file.
- OTP codes (coursetable) ride in tool **arguments**, which are not serialized into conversation — only tool **results** are.
- `secrets/treehole/session.json` tokens are not folded into conversation or the long-term session store.

*Over-flagged — not real risks:*
- Plaintext creds under `secrets/plib/`, `secrets/treehole/` are **by design** (gitignored local creds, per `docs/setup_zh.md`), not a leak. No action.
- The DashScope embedder (`src/rag/embedder.py`) is **retired/unregistered** (doc base replaced RAG); it's not in any live path. No action.

*Genuine must-fix (was: tool error string → LLM context + disk; FIXED 2026-06-29):*
- **The leak path.** A P-Lib error folded into `ToolResult.error` → `agent.py:176` writes `ERROR: {error}` into the conversation → next iteration ships it to DeepSeek/Kimi, and `session_store` persists it to `data/sessions/*.json`. If the plib/treehole library echoed a credential on an auth failure, it leaked.
  - **Fix applied:** `src/tools/redact.py` `redact(text, secrets)`; `PLibMaterialsTool._run` strips the held/passed P-Lib email+password and `TreeholeAuthService` strips the stored/in-scope IAAA id/password from every error string before it becomes a `ToolResult.error`. (Since the 2026-07-01 in-process migration this happens over library `PlibError`/`TreeholeError` exceptions, not subprocess stderr — the redaction boundary is unchanged, and in-process structured errors are *less* likely to echo a secret than raw stderr was.) Covered by `tests/test_redact.py` (helper + plib + treehole boundary). **pku3b is not covered** — its portal password lives in pku3b's own `cfg.toml` and never enters our process, so we hold no value to strip; treat pku3b stderr as out of our control.

**Steps (your by-hand verification):**
1. **Leak probe (catches a leak that already happened).** After running `python -m src --online` for a session that exercised P-Lib / treehole (including any failed call), grep on-disk state for the literal secret:
   - `grep -rIF "$(cat secrets/plib/password)" data/ debug/ 2>/dev/null` → expect **no matches**.
   - `grep -rIF "$(cat secrets/treehole/password)" data/ debug/ 2>/dev/null` → expect **no matches**.
   - (If either matches, a credential is on disk in a conversation/cache file — confirms the leak path above.)
2. **LLM-context probe.** Trigger a deliberate P-Lib failure (e.g. temporarily wrong password), ask a follow-up question in the same chat, and confirm the model's reply does not surface the credential. Then `grep -rIF "$(cat secrets/plib/password)" data/sessions/` → expect no matches.
3. Regression confirm the fix end-to-end: after exercising a *failed* P-Lib / treehole call online, re-run steps 1–2 — expect no credential in `data/sessions/` and `***REDACTED***` where the error would have shown it.

**Automated**: `pytest tests/test_redact.py` (the `redact()` helper + `PLibMaterialsTool` and `TreeholeAuthService` boundaries strip a known secret from a synthetic error).

---

## Verified

_(empty — entries land here once the architect signs off)_
