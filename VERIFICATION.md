# VERIFICATION.md

Human-executable verification steps. Maintained by the `verification` skill. The architect (Rizzo) runs these to confirm a change is *real*, not just plausible — verification relocated off the code and onto observable behavior. "Looks plausible" is the danger zone, not the safe zone.

**How to use.** Work the **Pending** queue top-down: run each step, check the observed result against the expected one. When satisfied, move the entry to **Verified** (or tell the agent to collapse it). Steps marked `[agent- run]` were already run by the agent; the rest are yours.

---

## Pending verification

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

*Genuine must-fix (verified by hand):*
- **Subprocess stderr can carry credentials into LLM context + disk.** `run_plib` folds `proc.stderr` into the error string (`plib_materials.py:260-261, 268`) → `ToolResult.error` → `agent.py:176` writes `ERROR: {error}` into the conversation → next iteration `_messages_for_llm()` (`agent.py:88`) ships it to DeepSeek/Kimi, and `session_store` persists it to `data/sessions/*.json`. If `plib-cli` (or `pku3b`, or the treehole lib) ever echoes a credential on an auth failure, it leaks. Same pattern: `pku3b_{coursetable,assignments,announcements}.py` stderr, `treehole_updates.py` AuthError messages.
  - **Recommended fix (NOT yet applied — gated on your go):** sanitize subprocess stderr/exception text before it becomes a `ToolResult.error` — strip the known credential values (the env-injected `PLIB_EMAIL`/`PLIB_PASSWORD`, treehole id/password) from any error string. One shared `redact(text, secrets)` helper at the subprocess-wrapper boundary covers all three tools.

**Steps (your by-hand verification):**
1. **Leak probe (catches a leak that already happened).** After running `python -m src --online` for a session that exercised P-Lib / treehole (including any failed call), grep on-disk state for the literal secret:
   - `grep -rIF "$(cat secrets/plib/password)" data/ debug/ 2>/dev/null` → expect **no matches**.
   - `grep -rIF "$(cat secrets/treehole/password)" data/ debug/ 2>/dev/null` → expect **no matches**.
   - (If either matches, a credential is on disk in a conversation/cache file — confirms the leak path above.)
2. **LLM-context probe.** Trigger a deliberate P-Lib failure (e.g. temporarily wrong password), ask a follow-up question in the same chat, and confirm the model's reply does not surface the credential. Then `grep -rIF "$(cat secrets/plib/password)" data/sessions/` → expect no matches.
3. Decide on the recommended fix above. If applied, re-run steps 1–2 and add an automated test asserting `redact()` strips a known secret from a synthetic stderr string.

**Automated**: none yet — the redaction fix (if taken) should ship with a unit test on the `redact()` boundary.

---

## Verified

_(empty — entries land here once the architect signs off)_
