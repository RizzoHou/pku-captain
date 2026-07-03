"""校内信息门户 client: identity (portal2017) and coursetable (portalPublicQuery).

These are two independent IAAA apps with separate sessions; neither shares
cookies with Blackboard. Faithful port of pku3b's ``api/low_level/portal.rs`` +
``api/portal.rs``.
"""

from __future__ import annotations

import json

from .config import Credentials
from .errors import AuthError, ParseError
from .http import HttpClient
from .iaaa import oauth_login, require_otp
from .models import CourseTable, Identity

# portalPublicQuery — course table
PORTAL_APP_ID = "portalPublicQuery"
PORTAL_REDIR = "https://portal.pku.edu.cn/publicQuery/ssoLogin.do"
PORTAL_HOME = "https://portal.pku.edu.cn/publicQuery/"
XNDXQ_LIST = "https://portal.pku.edu.cn/publicQuery/ctrl/topic/myCourseTable/getXndXqList.do"
COURSE_INFO = "https://portal.pku.edu.cn/publicQuery/ctrl/topic/myCourseTable/getCourseInfo.do"

# portal2017 — identity. NB: use the normalized https ssoLogin.do; the
# login.jsp/../ssoLogin.do form yields IAAA error E12.
PORTAL2017_APP_ID = "portal2017"
PORTAL2017_REDIR = "https://portal.pku.edu.cn/portal2017/ssoLogin.do"
PORTAL2017_BASIC_INFO = "https://portal.pku.edu.cn/portal2017/account/getBasicInfo.do"

# camelCase portal key -> Identity attribute (snake_case).
_IDENTITY_MAP = {
    "name": "name",
    "studentId": "student_id",
    "sex": "sex",
    "userIdentity": "user_identity",
    "department": "department",
    "studentType": "student_type",
    "speciality": "speciality",
    "direction": "direction",
    "politics": "politics",
    "ethnic": "ethnic",
    "nativePlace": "native_place",
}


def _empty_as_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "null":
        return None
    return text


def identity_from_payload(payload: dict) -> Identity:
    """Map a ``getBasicInfo.do`` JSON payload into an :class:`Identity`.

    Requires ``success`` to be truthy; empty strings and the literal ``"null"``
    normalize to ``None`` (both forms occur in portal responses).
    """
    if not payload.get("success"):
        raise AuthError("portal returned an unsuccessful identity response")
    fields = {
        attr: _empty_as_none(payload.get(key)) for key, attr in _IDENTITY_MAP.items()
    }
    return Identity(**fields)


class PortalClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    # -- identity (portal2017) ---------------------------------------------

    def require_otp_identity(self, username: str) -> bool:
        return require_otp(self.http, PORTAL2017_APP_ID, username)

    def get_identity(self, creds: Credentials, otp_code: str = "") -> Identity:
        self._portal2017_login(creds, otp_code)
        res = self.http.post(PORTAL2017_BASIC_INFO)
        if not res.ok:
            raise AuthError(f"getBasicInfo failed: HTTP {res.status_code}")
        try:
            payload = res.json()
        except ValueError as exc:
            raise ParseError("identity response was not JSON") from exc
        return identity_from_payload(payload)

    def _portal2017_login(self, creds: Credentials, otp_code: str) -> None:
        require_otp(self.http, PORTAL2017_APP_ID, creds.username)
        token = oauth_login(
            self.http,
            appid=PORTAL2017_APP_ID,
            username=creds.username,
            password=creds.password,
            otp_code=otp_code,
            redir=PORTAL2017_REDIR,
        )
        self.http.get(PORTAL2017_REDIR, params={"token": token}, allow_redirects=True)

    # -- course table (portalPublicQuery) ----------------------------------

    def require_otp_coursetable(self, username: str) -> bool:
        return require_otp(self.http, PORTAL_APP_ID, username)

    def get_coursetable(self, creds: Credentials, otp_code: str = "") -> CourseTable:
        self._portal_login(creds, otp_code)

        xndxq_res = self.http.get(XNDXQ_LIST)
        if not xndxq_res.ok:
            raise AuthError(f"getXndXqList failed: HTTP {xndxq_res.status_code}")
        try:
            xndxq_json = xndxq_res.json()
        except ValueError as exc:
            raise ParseError("xndxq list was not JSON") from exc
        term = None
        now = xndxq_json.get("nowXnxq") if isinstance(xndxq_json, dict) else None
        if isinstance(now, dict):
            term = now.get("xndxq")

        info_res = self.http.get(COURSE_INFO, params={"xndxq": term or ""})
        if not info_res.ok:
            raise AuthError(f"getCourseInfo failed: HTTP {info_res.status_code}")
        raw_text = info_res.text
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ParseError("course info was not JSON") from exc
        return CourseTable(term=term, raw=raw)

    def _portal_login(self, creds: Credentials, otp_code: str) -> None:
        require_otp(self.http, PORTAL_APP_ID, creds.username)
        token = oauth_login(
            self.http,
            appid=PORTAL_APP_ID,
            username=creds.username,
            password=creds.password,
            otp_code=otp_code,
            redir=PORTAL_REDIR,
        )
        self.http.get(PORTAL_REDIR, params={"token": token}, allow_redirects=True)
        verify = self.http.get(PORTAL_HOME)
        if not verify.ok:
            raise AuthError("portal login verification failed")
