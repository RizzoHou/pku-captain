"""Every treehole / IAAA URL and the magic strings, in ONE module.

This is an unofficial, drifting API. When the platform changes a path or the
appid, this is the single file to edit — nothing else should hard-code a URL.
See docs/treehole-protocol.md for how each of these was reverse-engineered.
"""

from __future__ import annotations

# --- IAAA central SSO ---------------------------------------------------------
IAAA = "https://iaaa.pku.edu.cn/iaaa"
IAAA_IS_MOBILE = f"{IAAA}/isMobileAuthen.do"   # GET: does this account force mobile OTP?
IAAA_OAUTH_LOGIN = f"{IAAA}/oauthlogin.do"     # POST: the ONLY call that counts toward E21

# appid for treehole. Note the literal space — it is part of the value, not a typo.
APPID = "PKU Helper"

# --- treehole --------------------------------------------------------------------
TREEHOLE = "https://treehole.pku.edu.cn"
# The axios baseURL is window.origin + "/chapi/". Endpoint strings are "/api/v3/...".
# Hitting /api/v3 WITHOUT the /chapi prefix returns 404 — the prefix is mandatory.
BASE = f"{TREEHOLE}/chapi"

REDIRECT_IAAA = f"{BASE}/redirect_iaaa_login"  # step 1: kicks off OAuth, sets session cookies

# Auth / verification
SEND_SMS = f"{BASE}/api/jwt_send_msg"          # POST (no body): triggers SMS to bound phone
VERIFY_SMS = f"{BASE}/api/jwt_msg_verify"      # POST form: valid_code=<4-digit>

# Reads
USERS_INFO = f"{BASE}/api/v3/users/info"       # POST; NOT gated by SMS verification
BOOKMARK_LIST = f"{BASE}/api/v3/bookmark/list"  # GET; NOT gated; the 关注 groups
HOLE_LIST = f"{BASE}/api/v3/hole/list"         # GET; gated; is_follow=1 → the 关注 list;
#                                                keyword=<kw> → search (verified 2026-06).
#                                                SPA also passes label / bookmark_id and a
#                                                #<pid> exact-lookup, unverified on chapi v3.
HOLE_GET = f"{BASE}/api/v3/hole/get"           # GET; gated; one hole by pid
COMMENT_LIST = f"{BASE}/api/v3/comment/list"   # GET; gated; replies of a hole

# 关注 write actions (POST) — not used by the monitor, kept here for completeness.
HOLE_ATTENTION = f"{BASE}/api/v3/hole/attention"             # follow: pid
HOLE_ATTENTION_CANCEL = f"{BASE}/api/v3/hole/attention_cancel"  # unfollow: pid (comma-sep for bulk)
HOLE_ATTENTION_UPDATE = f"{BASE}/api/v3/hole/attention_update"  # move group: pid, bookmark_id

# --- device identity ----------------------------------------------------------
# The SPA sends header uuid = UUID_PREFIX + <e>, where <e> is the same id passed to
# redirect_iaaa_login. The SMS-verified state binds to this string — see protocol doc.
UUID_PREFIX = "Web_PKUHOLE_2.0.0_WEB_UUID_"

# Browser-shaped UA. Anti-abuse hygiene, not an auth factor.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# --- response codes (observed) -------------------------------------------------
CODE_OK = 20000
CODE_NEED_SMS = 40002        # 请手机短信验证 — content gate
CODE_ANTI_ADDICTION = 41511  # 防沉迷 (may block at night)
CODE_HOLE_NOT_FOUND = 41001  # 树洞不存在
