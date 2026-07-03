# VERIFICATION.md

Human-executable verification steps. Maintained by the `verification` skill. The architect (Rizzo) runs these to confirm a change is *real*, not just plausible — verification relocated off the code and onto observable behavior. "Looks plausible" is the danger zone, not the safe zone.

**How to use.** Work the **Pending** queue top-down: run each step, check the observed result against the expected one. When satisfied, move the entry to **Verified** (or tell the agent to collapse it). Steps marked `[agent- run]` were already run by the agent; the rest are yours.

---

## Pending verification

### 2026-07-03 — Universal 账号中心 + configurable model endpoints

**Proves**: one 账号 button opens a tabbed login page that (a) logs into treehole (IAAA + SMS), (b) *persists* P-Lib creds so they survive a restart, and (c) configures the two model roles (文本模型/视觉模型) with custom endpoints — DeepSeek/Kimi as defaults. Existing checkouts keep working via the legacy-key fallback; the app never ships with the dev's creds.

**Steps**:
1. `[agent-run]` `pytest tests/` → **396 passed, 2 skipped** (adds `test_credentials.py`, `test_login_dialog.py`; updates bootstrap/gating/dialog suites).
2. `[agent-run]` Real DeepSeek round-trip through the *new* construction path: `.venv/bin/python -c "from src.core import build_agent; a=build_agent(offline=False); print([e.payload.get('text') for e in a.turn('Reply with exactly: pong') if e.kind=='final'])"` → expect `['pong']` (proves `build_chat_llm` reads endpoint/model/key from `CredentialStore`, legacy `secrets/api_keys/deepseek_key.txt` honoured). Also `[agent-run]` `python scripts/smoke_deepseek.py` → **passed**.
3. **First-run / offline (no `secrets/models.json`, no keys)**: `python -m src` → the chat shows a startup notice pointing to 账号 (「点击右上角『账号』…」) and does **not** crash. Click 账号 → the dialog opens (offline) with the 模型配置 tab editable.
4. **Configure a model endpoint**: in 账号 → 模型配置, set the 文本模型 API 密钥 (leave 接口地址/模型名称 at their DeepSeek defaults) → 保存模型配置 → expect "已保存模型配置，重启应用后生效". Confirm `secrets/models.json` now exists with a `text` entry. Restart `python -m src --online` → chat works, header model switcher shows 文本模型 / 视觉模型 (not DeepSeek/Kimi).
5. **Custom endpoint (optional)**: set 文本模型 接口地址 to an OpenAI-compatible proxy + its model name → save, restart → chat routes to that endpoint (DeepSeek/Kimi are only defaults).
6. **P-Lib persistence fix**: 账号 → P-Lib, enter email+password → 保存并登录 → expect "登录成功并已保存凭据". **Quit and relaunch** `python -m src --online`, ask "P-Lib 今天还能下载几次？" → expect a quota number *without* re-entering credentials (old dialog lost them on restart; this is the fix). Confirm `secrets/plib/{email,password}` exist.
7. **Treehole via account center (online)**: 账号 → 统一身份·树洞, enter 学号+密码 → 登录 → 发送验证码 → enter SMS → 完成验证 → expect "短信验证完成…". Then the dashboard 树洞 card populates. The 树洞新消息 dialog's 登录/管理 button opens the same account center (no inline login form remains).
8. **Vision auto-switch still works**: on 文本模型, ask a 培养方案 question → expect "已自动切换到视觉模型并开启新对话" and a correct doc-read answer (role rename didn't break `VisionRouter`).
9. **Negative**: offline, click 账号 → 统一身份 tab is disabled with a "需要在线模式" note; P-Lib save still writes creds (no crash, no validation).

**Automated**: `pytest tests/test_credentials.py tests/test_login_dialog.py tests/test_bootstrap_docbase.py tests/test_dashboard_gating.py` (store read/write/legacy-fallback/clear; dialog persist + emit + offline-disabled treehole; role-keyed model builders; account dialog opens offline un-gated).

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
