# PKU Treehole — Auth & API Protocol (reverse-engineered)

End-to-end record of how `treehole.pku.edu.cn` authenticates and serves data, reconstructed by inspecting the web SPA bundle and verified live against a real account on 2026-06-01. This is the foundation `pku-treehole-cli` is built on. Everything below was confirmed empirically unless marked **(unverified)**.

Discovery scripts that produced these results live in `scripts/`: `probe_login.py` (IAAA login chain), `probe_data.py` (authenticated reads), `verify_sms.py` (SMS gate + persistence poll). No credentials appear in this document; the scripts read them from the gitignored `secrets/`.

## Platform shape

- **Frontend**: a Vue SPA served at `https://treehole.pku.edu.cn/ch/web/`, single bundle `/ch/web/assets/index-4b35b394.js` (~1.5 MB). All endpoint paths, the auth flow, and the request headers below were read out of this bundle.
- **Backend**: Laravel (PHP). Identifiable by `XSRF-TOKEN` + `_session` cookies (Laravel-encrypted JSON, `Max-Age` 7200 = 2h) and the default Laravel 404 / 405 error pages.
- **API base**: the axios instance uses `baseURL = window.origin + "/chapi/"`. Endpoint strings in the bundle look like `/api/v3/...`, and axios joins them to `https://treehole.pku.edu.cn/chapi/api/v3/...`. **The `/chapi` prefix is mandatory** — hitting `/api/v3/...` directly returns 404. This cost an hour during discovery.
- **Response envelope**: `{ "code": 20000, "data": { "list": [...], "total": N } | {...}, "message": "success", "success": true, "timestamp": <unix> }`. Errors keep the same shape with `success: false` and a non-20000 `code`.

## The authentication chain

PKU's central SSO (IAAA) fronts treehole. The full handoff is five HTTP steps, no browser required.

```
SPA generates a device id `e`, stores localStorage pku-uuid = "Web_PKUHOLE_2.0.0_WEB_UUID_" + e
   │
   ▼
1. GET  https://treehole.pku.edu.cn/chapi/redirect_iaaa_login?version=3&uuid=<e>&plat=web
        → sets cookies XSRF-TOKEN + _session ; 302 to IAAA oauth.jsp
   │
   ▼
2. IAAA oauth page:  appID = "PKU Helper"  (note the space)
        redirectUrl = https://treehole.pku.edu.cn/chapi/cas_iaaa_login?version=3&uuid=<e>&plat=web
   │
   ▼
3. GET  https://iaaa.pku.edu.cn/iaaa/isMobileAuthen.do?appId=PKU Helper&userName=<uid>&_rand=<rand>
        → { "authenMode": "否", "isMobileAuthen": false, "mobileMask": "<masked>", "isBind": true }
        "否" ⇒ NO IAAA-level mobile OTP for this appid; plain password login is allowed.
   │
   ▼
4. POST https://iaaa.pku.edu.cn/iaaa/oauthlogin.do        (application/x-www-form-urlencoded)
        appid=PKU Helper  userName=<uid>  password=<plaintext>  randCode=  smsCode=  otpCode=  redirUrl=<step-2 redirectUrl>
        → { "success": true, "token": "<32-hex IAAA one-time token>" }
        Password is sent in plaintext (no RSA for this appid). No captcha (randCode empty).
   │
   ▼
5. GET  <redirectUrl>&token=<iaaa_token>
        → 302 → https://treehole.pku.edu.cn/ch/web/iaaa_success?is_mobile=0&token=<JWT>&expires_in=<ts>&uid=<uid>
        sets JSESSIONID cookie. The `token` query param IS the app JWT.
```

### IAAA error codes (from the SPA + observed)

| Code | Meaning | Consequence |
|---|---|---|
| `E01` | User ID or password incorrect | retry with correct creds |
| `E05` | OTP code incorrect | only if account forces OTP |
| `E21` | Too many attempts | **30-minute lockout** — do not brute-force |

Only `oauthlogin.do` (step 4) consumes a login attempt toward `E21`. A TLS/connection failure before a response is *not* an attempt, so retrying on transient network errors is safe. The `iaaa.pku.edu.cn` host was intermittently dropping TLS handshakes during testing; the client must retry connection errors.

### The app token (JWT)

The `token` from step 5 is an HS256 JWT, stored by the SPA in `localStorage.token` and sent as `Authorization: Bearer <JWT>`.

- Claims: `iss` = `.../chapi/cas_iaaa_login`, `sub` = `<uid>`, `iat`, `nbf`, `exp`, `jti`, `prv`.
- **Lifetime ≈ 30 days** (`exp - iat = 2,592,000s`). `expires_in` in the callback URL echoes `exp`.

## Device identity — the `uuid` header (the load-bearing finding)

Every `/chapi` API request carries a `uuid` header. From the bundle's request interceptor:

```js
e.headers.Authorization = `Bearer ${token}`
e.headers.uuid = localStorage.getItem("pku-uuid") || "94B7DB0A74D347E7A6B29AE9569079AC"
//               pku-uuid = "Web_PKUHOLE_2.0.0_WEB_UUID_" + e   (same e as the login ?uuid=)
```

This single string is the **entire** device identity — there is **no canvas / TLS / JS fingerprinting** anywhere in the bundle. On any auth failure the SPA does `localStorage.removeItem("pku-uuid")` + clear token, confirming the `uuid` is part of the auth identity.

The same `e` is used in two places and **must be kept consistent**: the login step's `?uuid=<e>` and the API header `uuid: "Web_PKUHOLE_2.0.0_WEB_UUID_<e>"`.

## SMS verification gate (`code 40002`)

After IAAA login the JWT is valid but **unverified**. Content endpoints return:

```json
{ "code": 40002, "message": "请手机短信验证", "success": false }
```

Metadata endpoints (`users/info`, `bookmark/list`) work *without* verification — only content reading (`hole/list`, `hole/get`, `comment/list`) is gated. On 40002 the SPA routes to `/verification` (PC: `/pc/verification`, title "短信认证").

### Verification flow

```
POST https://treehole.pku.edu.cn/chapi/api/jwt_send_msg      (no body)
     → { "code": 20000, "message": "发送成功" }   and an SMS to the bound phone
POST https://treehole.pku.edu.cn/chapi/api/jwt_msg_verify    (form: valid_code=<code>)
     → { "code": 20000, "message": "success" }
```

Observed SMS code: **4 digits**. Send these requests with the same `uuid` header used for reads.

### Verified state binds to the `uuid` (proven)

Isolation test on one live verified session, same JWT and cookies, back-to-back, the **only** variable being the `uuid` header:

| `uuid` header | `hole/list?is_follow=1` ×4 |
|---|---|
| absent | `40002` every call |
| present | `20000 success` every call |

A 7-minute poll with the header on stayed verified the whole time (vs. a ~2-minute window when the header was absent). Conclusion: **SMS verification binds to the `uuid` device id; the header must be sent on the verify call and on every subsequent request.** This is what lets a stable identity stay verified for as long as a browser session does (the account owner confirms browser sessions stay verified for a long time; exact re-challenge cadence over days is **unverified**).

A session verified in one sitting still read content **a day later** with no re-verification (confirmed when building the package), corroborating the long-lived window.

### Cookies are NOT required for reads (proven)

Same cached session, same JWT + `uuid` header, the only variable being the cookie jar:

| cookie jar | `hole/list?is_follow=1` |
|---|---|
| full (`JSESSIONID`, `XSRF-TOKEN`, `_session`) | `20000 success` |
| **cleared** | `20000 success` |

So the 2h-`Max-Age` Laravel `_session` cookie does **not** gate content reads — **identity = `jwt` + `uuid` is sufficient.** An unattended monitor does not need a human every 2h. Cookies are still persisted (for write actions / API-drift insurance) but the read path does not depend on them.

## Authenticated API map

Base: `https://treehole.pku.edu.cn/chapi`. All requests below need `Authorization: Bearer <JWT>` + `uuid: <header>` + the cookie jar; content endpoints additionally need SMS verification.

### Reads

| Purpose | Method + path | Key params | Notes |
|---|---|---|---|
| whoami | `POST /api/v3/users/info` | — | not gated; returns `uid, name, gender, userIdentity, department, newmsgcount, …` |
| 关注 groups | `GET /api/v3/bookmark/list` | `page, limit` | not gated; group = `{bookmark_name, id, sort, hole_count}`; `id=-1` "全部", `id=""` 未分组 |
| **关注 list** | `GET /api/v3/hole/list` | **`is_follow=1`**, `page`, `limit`, optional `bookmark_id` | the marked-holes list; omit `bookmark_id` (or `-1`) for all groups |
| public timeline | `GET /api/v3/hole/list` | `page, limit` | same endpoint without `is_follow` |
| **search** | `GET /api/v3/hole/list` | **`keyword=<kw>`**, `page`, `limit` | keyword search over all holes — **not a separate route** (verified live 2026-06: `keyword=考试` returned only matching holes, code `20000`; ~30 guessed routes like `hole/search`, `search/*` all 404). SMS-gated like any content read. A bare-digit `keyword` stays a keyword (finds holes that *quote* that pid); use `hole/get` for exact-id lookup. The web SPA also passes `label` (tag), `bookmark_id` (group, with `is_follow=1`), and routes `#<num>` → `pid` — **unverified on chapi v3**, deferred. |
| one hole | `GET /api/v3/hole/get` | `pid` | `hole/one` is an alternative |
| comments | `GET /api/v3/comment/list` | `pid, page, limit` | reply list; `hole/list_comments` is an alternative |

`hole/list` is GET only (POST → 405).

**Pagination quirk:** the `total` field is **not** the row count — it is a "there may be more" sentinel (≈ items-so-far + 1 on a full page; on the last/partial page it does not equal the real total). Paginate on **page fullness** (`len(list) < limit` ⇒ last page), never on `total`. The 关注 list of this account paginated to a stable 75 holes across `limit` 25/50/100 this way; trusting `total` (which read as low as 4) stops far short.

### 关注 write actions (POST)

| Action | Path | Body |
|---|---|---|
| follow | `/api/v3/hole/attention` | `pid` |
| unfollow | `/api/v3/hole/attention_cancel` | `pid` (comma-separated for bulk) |
| move to group | `/api/v3/hole/attention_update` | `pid, bookmark_id` |
| add / rename group | `/api/v3/bookmark/add` · `/api/v3/bookmark/update` | `bookmark_name` |

### Field reference

- **Hole** (list item / `hole/get`): `pid`, `text`, `timestamp`, **`reply`** (reply count), `likenum`, `is_follow`, `tag`, `attention_info{ pid, bookmark_id }`, `imageList`, `identity_info{ department, gender, level }`.
- **Comment** (`comment/list`): `cid`, `text`, `timestamp`, `name_tag`, `is_author`, `quote`, `imageList`.

### Other observed `code`s

`41511` 防沉迷 (anti-addiction gate — may block at night, **unverified** trigger), `42411` network exception, `41001` 树洞不存在.

## What this means for monitoring

The platform never pushes. The only model is **poll + diff**:

- The diff key per marked hole is the **`reply` count**; the latest comment `cid` is the cursor for fetching only the new replies. Compare against the last-seen values in local state.
- Store **minimal state** — `pid → { reply_count, last_cid, checked_at }` — never the comment text (anonymous campus speech; no reason to cache it locally).
- **Comment ordering (verified 2026-06):** `comment/list` is **oldest-first with monotonically-increasing `cid`** (and `timestamp`). The newest replies sit at the tail of the last page (`page ≈ ceil(reply / limit)`). Past-end pages return an empty `list` with code `20000` (not an error), so a tail-locating walk terminates safely. The monitor uses this: on a reply increase it fetches from the last page backward, emitting comments with `cid > last_cid`, then records the new max `cid`. On a hole's first observed growth (no cursor yet) it falls back to the newest `delta` comments. This is implemented in `src/treehole/monitor.py`.

## Session-maintenance model (the design contract)

1. **Identity bundle**, generated once and reused forever (gitignored): `uuid` (random `e`), the 30-day `jwt`, the cookie jar.
2. Send `Authorization: Bearer <jwt>` + `uuid: "Web_PKUHOLE_2.0.0_WEB_UUID_<e>"` on **every** request; keep one persistent cookie jar.
3. SMS-verify only on first setup and on a real `40002`. **Fail loud** — surface "needs SMS re-verification" and exit non-zero; never silently return an empty result, or a monitor an agent relies on will look "all caught up" when it is actually locked out.
4. **Poll gently** (anti-abuse hygiene, not the mechanism): conservative interval, jitter, a normal User-Agent, single account.

## Risks & open questions

- **Re-challenge cadence over days** is unverified — proven only to ≥7 minutes with a consistent `uuid` (plus one confirmed next-day read).
- **Expired-JWT response shape** is unconfirmed. The client's transparent re-login keys on HTTP `401`/`403`; if an expired JWT instead returns `200` + a non-20000 auth code, re-login never fires (it surfaces as `APIError`). Confirm the shape when a token actually expires (~30 days) before relying on unattended re-login.
- **Re-login does not clear `40002`** (untested but assumed): a freshly minted JWT under the same `uuid` may or may not skip SMS re-verification. The client deliberately never re-logins on `40002` (it would burn an E21 attempt for nothing).
- **Unofficial, drifting API** — treehole changes endpoints periodically. Keep every URL and the `appid` in one module so a break is a one-file fix.
- **Real-name account + aggressive polling** could trip anti-abuse or flag the account → conservative intervals, one account.
- **Credential sensitivity** — the IAAA password is the master PKU credential. Local plaintext is acceptable only for the testing stage; move to an OS keyring / encrypted store before any unattended use.
