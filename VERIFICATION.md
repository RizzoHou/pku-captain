# VERIFICATION.md

Human-executable verification steps. Maintained by the `verification` skill. The architect (Rizzo) runs these to confirm a change is *real*, not just plausible — verification relocated off the code and onto observable behavior. "Looks plausible" is the danger zone, not the safe zone.

**How to use.** Work the **Pending** queue top-down: run each step, check the observed result against the expected one. When satisfied, move the entry to **Verified** (or tell the agent to collapse it). Steps marked `[agent- run]` were already run by the agent; the rest are yours.

---

## Pending verification

### 2026-07-06 — Release bundle installs from the download zip (Mac)

**Proves**: a user who *only* downloads the Release asset (no git, no clone) gets a working app — the curated `pku-captain-1.0.0.zip` unzips, `install.sh` runs, and the app launches, with the doc base present.

**Steps (Mac, clean machine simulation)**:
1. Open https://github.com/RizzoHou/pku-captain/releases/latest → **Assets** → download `pku-captain-1.0.0.zip`. Expect ~80 MB.
2. Unzip → expect a single `pku-captain-1.0.0/` folder containing `README.md`, `install.sh`, `pyproject.toml`, `src/`, `vendor/`, `doc_base/` — and **no** `tests/`, `scripts/`, `docs/`, `.github/`, `.claude/`, `CLAUDE.md`, `DEVCHANGELOG.md`, `VERIFICATION.md`.
3. `cd pku-captain-1.0.0 && ./install.sh` → expect it to create `.venv`, install deps, and print the launch hint (1–2 min).
4. `.venv/bin/python -m src` → expect the window to open in 离线模式, no crash. `du -sh doc_base` → expect ~76 MB (doc base shipped, `doc_base/original/` absent).
5. Sanity that the README the user reads matches: `sed -n '1,20p' README.md` → expect the 快速安装（推荐） download-first flow, not a git-clone-first one.

**Automated / [agent-run] on Linux**: built the zip with `scripts/package_release.sh`; unzipped into a throwaway dir; `python -m venv` + `pip install -e .` in a fresh venv succeeded; `import src` and all four vendored packages (`plib_cli`, `dean`, `treehole`, `pypku3b`) import. Verified the archive contains only the six intended top-level entries and excludes `tests/`/`scripts/`/`docs/`/`.claude/`/`CLAUDE.md`. Mac cold-install + GUI launch is the human-only part.

### 2026-07-06 — PKUHub 下载 works again (405 → CSRF POST) (Mac)

**Proves**: after entering PKUHub credentials, a real file **download** succeeds instead of failing with HTTP 405 — pkuhub moved `/download/<id>` from GET to a CSRF-guarded POST, and the vendored client now matches it. Login + quota already worked (that's why this was easy to miss).

**Steps (Mac, in `~/Downloads/pku-captain`, re-prepared with this fix)**:
1. `.venv/bin/python -m src --online` → 设置 → **PKUHub** → enter 图书馆邮箱 + 密码 → 保存. Confirm the dashboard PKUHub card shows 今日剩余下载次数 (e.g. `10`) — proves login/quota (already worked).
2. **The fix — download**: in chat ask e.g. `帮我在 P-Lib 搜"高等数学"往年题，下载第一个`, or drive the tool directly. Expect a file to be **saved** (a `downloads/plib/<name>` path + `quota_remaining` decremented by 1), **not** an error containing `HTTP 405` or `download returned HTTP`.
3. **Sanity on disk**: `ls -la downloads/plib/` → expect the downloaded file present with non-zero size. Open it → expect a real document, not an HTML error page.
4. **Negative (optional)**: after exhausting the daily quota, a further download → expect the Chinese quota message (`今日剩余下载次数`/配额), still no 405.

**Automated / [agent-run] on Linux**: live-probed pkuhub — `GET /download/727` → `405 Allow: POST, OPTIONS`, unauth `POST` (no token) → `400`; confirmed the CSRF mechanism from the live `csrf_helper.js` (wraps `fetch` to add `X-CSRFToken`). Path-forced trace: `download()` issues one `POST /download/<id>` with `{X-CSRFToken}` + `retry=False`. Vendored `test_client.py` **6 pass** (new POST/CSRF contract test), pku-captain suite **473 pass / 3 skip**, ruff clean. No P-Lib creds on the Linux box, so the real end-to-end download is the human-only part.

### 2026-07-06 — Cold-start login on `--online` with no key + slim clone (Mac)

**Proves**: a brand-new install can reach and use the 统一身份·树洞 login the *first* time it launches — no key configured yet — instead of the old deadlock where `--online` fell to offline and disabled the login tab. Also that the shallow clone is materially faster.

**Steps (Mac, in `~/Downloads/pku-captain` prepared for you)**:
1. **Slim clone**: this dir was made with `git clone --depth 1` of branch `worktree-release-1.0-packaging`. Sanity: `du -sh doc_base` → expect ~80 MB (no `doc_base/original/`); `ls doc_base/original 2>/dev/null` → expect *no such directory*.
2. **Cold launch, zero keys**: with **no** `secrets/models.json` yet (fresh — don't copy old secrets), `.venv/bin/python -m src --online`. Expect the window to open in **在线模式** (title/first system line), with a chat note that the text-model key isn't configured (点击『设置』→ 模型配置). It must **not** say "已切换到离线模式".
3. **The fix — login is reachable**: click **设置** → **统一身份·树洞** tab → the 学号 / 密码 / 验证码 fields and 登录 button are **enabled** (not greyed), and there is **no** "树洞登录需要在线模式启动" banner. Enter your IAAA 学号+门户密码 → 登录 → complete SMS → expect 已登录 · <name>. (This is the exact step that was impossible before.)
4. **Brain swaps in live**: still in 设置 → 模型配置 → enter your DeepSeek text-model key → 保存 → close. Send a chat message → expect a real DeepSeek reply (not an echo), no restart.
5. **Negative**: plain `.venv/bin/python -m src` (offline) → 设置 → 统一身份·树洞 is *correctly* disabled with the "需要在线模式启动" hint — that message is now accurate only for genuine offline launches.

**Automated / [agent-run] on Linux**: full suite **473 pass / 3 skip**; `build_agent(offline=False)` against an empty secrets dir returns an `EchoLLMProvider`-brained agent with `treehole_updates` registered and `available_chat_models(offline=False) == []` (previously raised `FileNotFoundError` → offline fallback). Mac GUI cold-start is the human-only part.

### 2026-07-05 — 1.0.0 packaging: install.sh + in-process PDF render (Mac)

**Proves**: on macOS the app installs via the one-shot script and `doc_read` renders curriculum PDFs with **no poppler/`pdftoppm` installed** (the pypdfium2 wheel replaces it). This is the one path this repo's Linux CI can't confirm for a Mac release.

**Steps (Mac)**:
1. In a fresh clone: `./install.sh` → expect it to pick your Python ≥3.11, create `.venv`, and finish with "done. Launch PKU Captain with:". (`./install.sh --math` if you want chat LaTeX.)
2. **Render without poppler**: confirm poppler is absent or ignored — `which pdftoppm` may print nothing; the feature must still work. `.venv/bin/python -m src --online` → set the visual (Kimi) model in 设置 → open **文档库** → pick a 培养方案 doc → **让 Captain 阅读** → expect page images to be read and answered in the dialog (not a "缺少 PDF 渲染依赖" or "未找到 pdftoppm" error).
3. **Agent path**: on the visual model, ask a 培养方案 学分 question → Captain chains `doc_search`→`doc_read` and answers from the rendered pages (page images injected into chat).
4. **Negative**: if you ever see `缺少 PDF 渲染依赖 pypdfium2 / Pillow`, the wheel didn't install — re-run `./install.sh`; the app should not crash, just report it.

**Automated / [agent-run] on Linux**: clean `git clone` → `./install.sh` (35s, installed pku-captain 1.0.0 + pypdfium2 5.11 + Pillow 12.3) → unmocked `_render_pages` produced valid PNG data URIs + correct page count → offline `build_agent` booted → `ruff check src` clean + `pytest tests/` **460 passed / 3 skipped**. Mac wheel + Gatekeeper-free CLI run are the human-only part.

### 2026-07-05 — 设置 → 对话设置: configurable tool-call round limit (live-apply)

**Proves**: the agent's tool-call round limit is user-settable from a new 对话设置 tab, persists across restarts, and takes effect on the running chat without a restart.

**Steps**:
1. **Tab + persistence (offline GUI fine)**: `python -m src` → 设置 → the tab strip now has **对话设置** (between 模型配置 and 网络代理). Open it → a **工具调用轮数** spinbox (default 8, range 1–50) → set it to **2** → **保存对话设置** → expect the status line "已保存：工具调用轮数上限 2，即时生效。" and a status-bar note "已更新工具调用轮数上限：2".
2. **Survives restart**: `cat secrets/settings.json` → expect `{"tool_rounds": 2}`. Quit and relaunch `python -m src` → reopen 设置 → 对话设置 → the spinbox shows **2** (prefilled from disk).
3. **Live effect (online)**: `python -m src --online`, set the limit to **2** and save, then ask a question that forces several tool rounds (e.g. "查一下我最近的作业、课程通知和树洞新回复，一起总结"). Expect the reply to end with **"工具调用已达到上限（2 轮）。…"** rather than a full answer — proving the new cap is applied live (no restart). Reset it to 8 afterward for normal use.
4. **Negative / clamp**: a hand-edited `secrets/settings.json` with `{"tool_rounds": 999}` or garbage → app still launches and behaves as the clamped/default value (no crash).

**Automated**: `pytest tests/test_credentials.py tests/test_bootstrap_docbase.py tests/test_login_dialog.py tests/test_agent_settings_live_apply.py` (`[agent-run]` 473 pass / 3 skip — store round-trip/clamp/corrupt, build_agent wiring, tab persists+emits+prefill, sentinel→live-apply routing) + `[agent-run]` `python scripts/smoke_deepseek.py` passed.

### 2026-07-05 — P-Lib rebranded to PKUHub across the GUI

**Proves**: no user-visible "P-Lib" text remains; the rename is copy-only (login/credentials and download dirs still work).

**Steps**:
1. **Settings tab**: `python -m src` → 设置 → the materials tab reads **PKUHub** (not "P-Lib 图书"); its status line says "请输入 PKUHub 邮箱和密码"; the dialog subtitle and 网络代理 hint say **PKUHub**.
2. **Dashboard card + dialogs (online)**: `python -m src --online` → the 资料 card title reads **PKUHub 资料** with body "已接入 PKUHub 搜索与下载"; click **搜索资料** → the window title + heading read **PKUHub 资料搜索**; a detail/download prompt reads **PKUHub 详情 / 下载 PKUHub 资料**.
3. **Inline tool trace**: ask Captain to search course materials → the inline tool-call row reads "PKUHub 返回 N 条资料…" / "PKUHub 今日剩余下载次数…".
4. **Login still works (creds path unchanged)**: 设置 → PKUHub → enter email+password → 保存并登录 → expect success + quota; `ls secrets/plib/{email,password}` still written. Existing stored creds keep working (path is unchanged).
5. **Stale diagnostic gone**: launch offline (`python -m src`) with no keys → the first-run diagnostic no longer lists "plib：未在 PATH 中找到，P-Lib 搜索不可用"; the offline hint says "…登录北大统一身份、PKUHub 并配置对话模型。"
6. **Grep sanity**: `grep -rn 'P-Lib' src/ui/ | grep -v '#\|"""'` → only docstring lines (no runtime string literals shown to the user).

**Automated**: `pytest tests/test_login_dialog.py::test_settings_tabs_use_pkuhub_not_plib` (`[agent-run]` passed — tab reads PKUHub, no "P-Lib" in tab titles, 对话设置 present).

### 2026-07-04 — 历史通知 detail no longer shows the body under 发布时间

**Proves**: opening a history course notice whose body was leaking into its 发布时间 (the 标题/发布时间 "swap") now renders cleanly — no time line rather than the whole body under 发布时间.

**Repro / steps (entry-mac, online)**:
1. `python -m src --online` → 课程通知 card → 刷新 once → open **历史通知** → click **"【2026程设】大作业阶段性提交通知"** (or any notice that previously showed the body twice).
2. **Expected**: the detail shows 标题 + 课程 + the body, and **no** `发布时间：<body>` line (a genuine dated notice still shows its real 发布时间). The body is no longer duplicated into the time field.
3. Sanity: dated notices (e.g. ones that did show `发布时间：2026年…`) still show their real posted time — the fix only drops marker-less body blobs.

**No data reset needed** — detail recomputes `posted_at` live from `posted_time`, so pulling the fix is sufficient.

**Automated**: `pytest tests/test_pku3b_tools.py` (`test_posted_at_rejects_body_masquerading_as_time`, `test_announcement_detail_drops_body_posted_time`).

### 2026-07-04 — 今日简报 (morning briefing) removed

**Proves**: the feature is gone from both the dashboard and the agent toolset, without breaking the dashboard header or the generic workflow mechanism.

**Steps**:
1. `[agent-run]` `pytest tests/` → **458 passed, 3 skipped**; `agent.workflows.all()` is now `{"hello"}` (asserted by `test_workflow_tool.py`).
2. **Dashboard (offline or online)**: `python -m src` → the header has **no** 今日简报 button; the remaining header buttons (树洞 / 记忆 / 文档库 / 设置 …) are intact (grid reflowed, no gap); no console error on launch.
3. **Agent**: ask Captain "给我今天的简报" → it answers by calling the underlying tools directly (there is no `morning_briefing` tool anymore) and does not crash.

**Automated**: `pytest tests/test_workflow_tool.py` (registered workflows = `{"hello"}`; generic workflow-tool mechanism still covered).

### 2026-07-04 — 账号中心 renamed to 设置 + context-length unit selector (token / k / m)

**Proves**: the settings dialog is renamed 设置 (button + window title), and 上下文长度 now accepts a value in tokens / thousands / millions while still storing raw tokens.

**Steps**:
1. **Rename (offline GUI fine)**: `python -m src` → the dashboard header button reads **设置** (not 账号); clicking it opens a dialog titled **设置** with the four tabs (统一身份·树洞 / P-Lib / 模型配置 / 网络代理). The P-Lib/树洞 login *field* labels that say "账号" are unchanged (correct — those are field names).
2. **Unit selector**: 设置 → 模型配置 → the 上下文长度 field has a unit dropdown → enter `256` + **千 (k)** → 保存模型配置 → confirm `secrets/models.json` `text` entry has `"context_window": 256000`. Enter `1` + **百万 (m)** → `1000000`.
3. **Prefill round-trips**: reopen 设置 → a stored `1000000` shows unit **百万** / value **1** (load→save stable); a stored `500000` shows **千** / `500`.
4. **Blank ⇒ default** still works (key omitted from `models.json`).

**Automated**: `pytest tests/test_login_dialog.py` (`256` + k ⇒ `context_window=256000`; prefill picks the natural unit).

### 2026-07-04 — chat model output is selectable and copyable

**Proves**: users can select and copy Captain's chat answers (previously the bubble text was not selectable).

**Steps**:
1. **Select + copy (online or offline)**: send a message → drag-select the assistant reply text → right-click → **复制** (or Ctrl+C) → paste into another app → text matches. A link inside the reply still opens on click (selection didn't break links).
2. **Streaming bubble**: text is selectable while/after it streams.
3. **(optional, `math` extra installed)**: a LaTeX answer renders in the WebEngine view and its right-click menu now offers Copy.

**Automated**: `pytest tests/test_chat_panel_copy.py` (finalized/streaming/user body carries `TextSelectableByMouse`; links stay accessible).

### 2026-07-04 — headless GUI test framework (drive the real app like a person)

**Proves**: the whole app is now drivable end-to-end headlessly — a real `MainWindow` with the three worker `QThread`s pumped — offline by default, with an opt-in online mode against real `secrets/`.

**Steps**:
1. `[agent-run]` `pytest tests/gui/` → the offline smoke test builds a full `MainWindow(offline=True)`, drives a real chat turn through the `AgentWorker` thread and a real dashboard refresh through `DashboardWorker`, asserting the rendered result; the online test auto-skips.
2. **Opt-in online (real network + `secrets/`, entry-mac)**: `PKU_CAPTAIN_GUI_ONLINE=1 .venv/bin/pytest tests/gui/test_gui_online.py -s` → builds `MainWindow(offline=False)`, asserts it did **not** silently fall back to offline, drives a live turn + dashboard refresh. Costs tokens / hits the network (like the smoke scripts).
3. **Extending**: `tests/gui/README.md` documents the drive→wait→assert recipe for adding a GUI test when a new feature ships.

**Automated**: `pytest tests/gui/` (offline smoke; the online file is env-gated).

### 2026-07-04 — 模型配置 changes apply live on save (no restart)

**Proves**: editing a model role in 设置 → 模型配置 and saving takes effect on the running chat immediately — no app restart (previously model edits only applied next launch).

**Steps**:
1. `[agent-run]` `pytest tests/` → **448 passed, 2 skipped** (new `test_model_live_apply.py`, 10 offscreen-Qt cases); `[agent-run]` `python scripts/smoke_deepseek.py` → **passed**.
2. **Live apply (online)**: `python -m src --online`, send a chat message to confirm the current brain works → 设置 → 模型配置 → change 文本模型 模型名称 (or point 接口地址 at another OpenAI-compatible endpoint) → 保存模型配置 → close the dialog → expect a chat system note ("已更新模型配置…即时生效") and the header switcher + context meter refreshed. Send another message → expect it to use the new config **without restarting**.
3. **Same-role edit keeps history**: after step 2's save, the prior conversation is still present (config swap, not a new session).
4. **Newly-configured role appears**: with only 文本模型 configured, add a 视觉模型 key → save → expect 视觉模型 to appear in the header switcher without restart.
5. **Lost-key fallback**: clear the *active* role's key → save → expect a clean fallback to a configured role (new session, mirroring a manual switch), not a crash.
6. **No mid-turn swap**: while a turn is streaming, save a model change → expect the swap deferred/skipped (no mid-turn brain swap), no crash.
7. **Offline**: `python -m src` (offline), save a model change → no crash (no-op apply).

**Automated**: `pytest tests/test_model_live_apply.py` (the `"models"` sentinel emits the new signal; non-models keys don't; busy guard; offline no-op; lost-key fallback+reset; apply-failure keeps the current brain; end-to-end signal→slot).

### 2026-07-04 — user-configurable per-role context length

**Proves**: each chat role's context window is now user-settable in 模型配置 (not hardcoded per provider), so a custom model/endpoint drives the right context-meter size and budget estimate; blank keeps the provider default.

**Steps**:
1. `[agent-run]` `pytest tests/` → **448 passed, 2 skipped** (new `test_model_context_window.py`, 10 cases + credentials round-trip/back-compat); `[agent-run]` smoke → **passed** (context_usage window `1000000` = DeepSeek default when unset).
2. **Set a window (offline GUI is fine)**: `python -m src` → 设置 → 模型配置 → set 文本模型 上下文长度 to `500000` → 保存模型配置 → confirm `secrets/models.json` `text` entry now has `"context_window": 500000`.
3. **Meter reflects it (online)**: with 500000 saved, the header context meter denominator reads the configured window, not 1M. (`python -m src --online`; observe the context-usage meter — takes effect immediately thanks to the sibling live-apply change, else after restart.)
4. **Blank ⇒ default**: clear the 上下文长度 field → save → confirm the key is omitted from `models.json` and the meter returns to the provider default (DeepSeek 1M / Kimi 256k).
5. **Back-compat**: an existing `secrets/models.json` with only `{api_key,base_url,model}` (no `context_window`) still loads and uses the provider default (no crash, no migration).
6. **Invalid input tolerated**: type non-numeric text in 上下文长度 → save → treated as unset (default), no error/crash.

**Automated**: `pytest tests/test_model_context_window.py tests/test_credentials.py` (`model()` round-trips a set window; blank/absent/invalid ⇒ None ⇒ ClassVar default; `_build_role_provider` threads it so a provider built with 500000 reports 500000; old 3-field JSON loads).

### 2026-07-04 — 历史通知 detail via date-free content-stable ids (supersedes the date-inclusive attempt)

**Proves**: clicking a course notice in 历史通知 now shows its content instead of `announcement with id … not found`. Two earlier attempts failed: the all-term retry (the id was pypku3b's **positional** value, which shifts on any add/delete/reorder) and then a content hash over `(course_id, title, posted_date)` — which **still** failed in real use because pypku3b emits the 发布时间 for only ~half of announcements and the per-course scrape is TTL-cached ~1h, so store-time and show-time are different scrapes; the dated↔undated flip became a total hash mismatch (`announcement with id 7b1f39f01a937eb3 not found` — the captain's live repro). Fixed by deriving the id from **`(course_id, normalized_title)` only — no date** — so a re-listed notice always re-derives the same id.

**Steps**:
1. `[agent-run]` `pytest tests/` → **458 passed, 3 skipped** (adds the date-flip regression: list-with-date, then re-list undated / with a different date, still resolves — the case both prior fixes lacked; plus content-determinism, legacy dual-match, genuine-miss still errors).
2. **One-time migration (do this first on entry-mac)**: `rm -f data/announcement_history.json` → drops rows carrying the old date-inclusive / positional ids; they re-accumulate with the new date-free id on the next 课程通知 refresh. Without this, previously-seen rows keep the stale id and still miss.
3. **History detail (online, needs `secrets/pku/`)**: `python -m src --online`, wait for the 课程通知 card → refresh once so rows re-accumulate → click 历史通知 → pick the notice the bug reproduced on (【2026程设】大作业阶段性提交通知) → expect the detail window to load its body, with **no** `教学网详情获取失败` note.
4. **Recent-card rows unchanged**: click a notice directly on the 课程通知 最近 list → detail loads, full body, as before.
5. **Negative (residual, expected)**: a notice whose course rotated fully out of both current-term and all-term lists (教学网 no longer serves it) still shows the stored fields + a `（教学网详情获取失败：…）` note — not tool-layer-fixable. Also: two notices with the *same title in one course* now share an id (rare; the intermittent date didn't reliably distinguish them either).

**Automated**: `pytest tests/test_pku3b_tools.py` (stable id is a pure function of `(course_id, title)`; a notice re-listed with a *different or absent* date still resolves; a genuine miss still errors; a legacy positional id dual-matches when it hasn't drifted).

### 2026-07-04 — 网络代理 (proxy modes) in the 账号中心

**Proves**: the app's *entire* network path (教学网 / 树洞 / P-Lib / 教务 / 模型接口 — vendored libs included) follows one user-set proxy mode from the new 账号中心 fourth tab, immediately on save, independent of the macOS system proxy. Best exercised on entry-mac (mihomo on `127.0.0.1:7890`, off-intranet).

**Steps**:
1. `[agent-run]` `pytest tests/` → **419 passed, 2 skipped** (new `test_network_config.py` + 2 dialog tests); `ruff` clean; `python scripts/smoke_deepseek.py` → **passed** (proxy apply sits at the top of `build_agent`).
2. `[agent-run]` Live mechanism probe on entry-mac (off-intranet, mihomo up): through `apply_proxy`, **manual** mode fetched intranet-only `https://pkuhub.cn` via `127.0.0.1:7890` → **HTTP 200**; **direct** mode → **ConnectTimeout** (correctly no proxy). Known upstream quirk: `course.pku.edu.cn` through this mihomo tunnel currently dies mid-TLS-handshake **even from `curl`** (`SSL_ERROR_SYSCALL`) — that's the proxy's routing, not the app; retest when the tunnel is healthy.
3. **GUI tab**: `python -m src` (offline is fine) → 设置 → 网络代理 tab. Expect three radios (跟随系统代理 default-checked on first run), the 代理地址 field greyed out until 自定义代理 is selected. Select 自定义代理, enter `127.0.0.1:7890`, 保存代理设置 → expect status "已保存代理设置，立即生效。" and the field normalised to `http://127.0.0.1:7890`. Confirm `secrets/network.json` now holds `{"mode": "manual", "url": "http://127.0.0.1:7890"}`.
4. **Manual mode end-to-end (entry-mac, off-intranet, hotspot + mihomo)**: `python -m src --online` with 自定义代理 `http://127.0.0.1:7890` saved → expect the P-Lib card (pkuhub.cn is intranet-only) to load real data, which is impossible without the proxy. Cards whose upstreams the tunnel currently breaks (see step 2) may still error — with a Chinese message, not a crash.
5. **Immediate effect, no restart**: with the app running and P-Lib erroring under 直连, switch to 自定义代理 → save → the dashboard re-polls its network cards automatically (the `network` sentinel) → P-Lib card recovers without relaunching.
6. **Direct mode isolation (the "SSL errors" scenario)**: turn the *system-level* proxy ON (mihomo global), then in-app select 直连（忽略系统代理） → save → on-intranet PKU cards must behave exactly like the proxy-less WiFi runs (the app no longer inherits the system proxy); off-intranet, intranet cards must fail with a clean Chinese error.
7. **Persistence**: quit and relaunch → 设置 → 网络代理 still shows the saved mode + URL (the mode applies from startup via `build_agent`).
8. **Known limit (expected, not a bug)**: the macOS 树洞消息通知 LaunchAgent daemon is a separate process and does **not** follow this setting.

**Automated**: `pytest tests/test_network_config.py tests/test_login_dialog.py` (store round-trip + corrupt-file fallback, per-mode env application, system-mode snapshot restore, the pinned `requests` env-proxy behavior, `build_agent` wiring, tab persist/apply/emit + URL gating).

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

### 2026-07-03 — Universal 账号中心 + configurable model endpoints

**Proves**: one 账号 button opens a tabbed login page that (a) logs into treehole (IAAA + SMS), (b) *persists* P-Lib creds so they survive a restart, and (c) configures the two model roles (文本模型/视觉模型) with custom endpoints — DeepSeek/Kimi as defaults. Existing checkouts keep working via the legacy-key fallback; the app never ships with the dev's creds.

**Steps**:
1. `[agent-run]` `pytest tests/` → **396 passed, 2 skipped** (adds `test_credentials.py`, `test_login_dialog.py`; updates bootstrap/gating/dialog suites).
2. `[agent-run]` Real DeepSeek round-trip through the *new* construction path: `.venv/bin/python -c "from src.core import build_agent; a=build_agent(offline=False); print([e.payload.get('text') for e in a.turn('Reply with exactly: pong') if e.kind=='final'])"` → expect `['pong']` (proves `build_chat_llm` reads endpoint/model/key from `CredentialStore`, legacy `secrets/api_keys/deepseek_key.txt` honoured). Also `[agent-run]` `python scripts/smoke_deepseek.py` → **passed**.
3. **First-run / offline (no `secrets/models.json`, no keys)**: `python -m src` → the chat shows a startup notice pointing to 账号 (「点击右上角『账号』…」) and does **not** crash. Click 设置 → the dialog opens (offline) with the 模型配置 tab editable.
4. **Configure a model endpoint**: in 设置 → 模型配置, set the 文本模型 API 密钥 (leave 接口地址/模型名称 at their DeepSeek defaults) → 保存模型配置 → expect "已保存模型配置，重启应用后生效". Confirm `secrets/models.json` now exists with a `text` entry. Restart `python -m src --online` → chat works, header model switcher shows 文本模型 / 视觉模型 (not DeepSeek/Kimi).
5. **Custom endpoint (optional)**: set 文本模型 接口地址 to an OpenAI-compatible proxy + its model name → save, restart → chat routes to that endpoint (DeepSeek/Kimi are only defaults).
6. **P-Lib persistence fix**: 设置 → P-Lib, enter email+password → 保存并登录 → expect "登录成功并已保存凭据". **Quit and relaunch** `python -m src --online`, ask "P-Lib 今天还能下载几次？" → expect a quota number *without* re-entering credentials (old dialog lost them on restart; this is the fix). Confirm `secrets/plib/{email,password}` exist.
7. **Treehole via account center (online)**: 设置 → 统一身份·树洞, enter 学号+密码 → 登录 → 发送验证码 → enter SMS → 完成验证 → expect "短信验证完成…". Then the dashboard 树洞 card populates. The 树洞新消息 dialog's 登录/管理 button opens the same account center (no inline login form remains).
8. **Vision auto-switch still works**: on 文本模型, ask a 培养方案 question → expect "已自动切换到视觉模型并开启新对话" and a correct doc-read answer (role rename didn't break `VisionRouter`).
9. **Negative**: offline, click 设置 → 统一身份 tab is disabled with a "需要在线模式" note; P-Lib save still writes creds (no crash, no validation).

**Automated**: `pytest tests/test_credentials.py tests/test_login_dialog.py tests/test_bootstrap_docbase.py tests/test_dashboard_gating.py` (store read/write/legacy-fallback/clear; dialog persist + emit + offline-disabled treehole; role-keyed model builders; account dialog opens offline un-gated).

---

## Verified

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
