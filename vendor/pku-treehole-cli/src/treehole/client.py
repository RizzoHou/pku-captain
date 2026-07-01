"""TreeholeClient — authenticated reads + the SMS-verification calls.

Wraps a requests.Session carrying the identity headers. The transport is
injectable so the client (and anything built on it) is testable without live
PKU calls.

Failure contract (fail loud):
  * code 40002 on a content read  -> NeedSMSVerification (a human must re-verify;
    re-login does NOT clear this and would burn an E21 attempt, so we never retry).
  * HTTP 401/403                   -> one transparent re-login if a relogin
    callback was supplied, else AuthError.
  * any other non-success code     -> APIError.
"""

from __future__ import annotations

from typing import Any, Callable

import requests

from . import endpoints
from .errors import APIError, AuthError, NeedSMSVerification
from .session import Identity, SessionStore


class TreeholeClient:
    def __init__(
        self,
        identity: Identity,
        *,
        store: SessionStore | None = None,
        relogin: Callable[[], Identity] | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        self.identity = identity
        self._store = store
        self._relogin = relogin
        self._timeout = timeout
        self._session = session or requests.Session()
        self._apply_identity()

    # --- identity / headers ---------------------------------------------------
    def _apply_identity(self) -> None:
        self._session.headers.update({
            "User-Agent": endpoints.USER_AGENT,
            "Accept": "application/json",
            "Authorization": f"Bearer {self.identity.jwt}",
            "uuid": self.identity.uuid_header,
        })
        for k, v in (self.identity.cookies or {}).items():
            self._session.cookies.set(k, v)

    def _do_relogin(self) -> None:
        if self._relogin is None:
            raise AuthError("401 from treehole and no relogin callback configured")
        self.identity = self._relogin()  # at most once per request; no loop
        self._apply_identity()
        if self._store is not None:
            self._store.save(self.identity)

    # --- request core ---------------------------------------------------------
    def _request(self, method: str, url: str, **kw: Any) -> Any:
        kw.setdefault("timeout", self._timeout)
        resp = self._session.request(method, url, **kw)
        if resp.status_code in (401, 403) and self._relogin is not None:
            self._do_relogin()
            resp = self._session.request(method, url, **kw)  # retry exactly once
        return self._unwrap(resp, url)

    @staticmethod
    def _unwrap(resp: requests.Response, url: str) -> Any:
        if resp.status_code in (401, 403):
            raise AuthError(f"{resp.status_code} from {url} (JWT invalid/expired)")
        try:
            body = resp.json()
        except ValueError:
            raise APIError(f"non-JSON response from {url}", path=url) from None
        code = body.get("code")
        if code == endpoints.CODE_NEED_SMS:
            raise NeedSMSVerification(body.get("message") or "请手机短信验证")
        if code != endpoints.CODE_OK or body.get("success") is False:
            raise APIError(body.get("message") or f"code {code}", code=code, path=url)
        return body.get("data", body)

    def _get(self, url: str, **params: Any) -> Any:
        return self._request("GET", url, params=params)

    def _post(self, url: str, data: dict[str, Any] | None = None) -> Any:
        return self._request("POST", url, data=data)

    # --- reads: metadata (NOT SMS-gated) -------------------------------------
    def users_info(self) -> dict[str, Any]:
        """whoami: uid, name, gender, department, newmsgcount, ..."""
        return self._post(endpoints.USERS_INFO)

    def bookmarks(self, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        """关注 groups. id=-1 全部, id="" 未分组."""
        data = self._get(endpoints.BOOKMARK_LIST, page=page, limit=limit)
        return data.get("list") or []

    # --- reads: content (SMS-gated) ------------------------------------------
    def followed(
        self, *, bookmark_id: int | str | None = None, page: int = 1, limit: int = 25
    ) -> dict[str, Any]:
        """One page of the 关注 list. Returns the raw {list, total} data dict.

        NB: `total` is NOT the followed-hole count — it's a "there may be more"
        sentinel (~items-so-far + 1 on a full page). Paginate on page fullness,
        never on `total`. See followed_all."""
        params: dict[str, Any] = {"is_follow": 1, "page": page, "limit": limit}
        if bookmark_id not in (None, -1):
            params["bookmark_id"] = bookmark_id
        return self._get(endpoints.HOLE_LIST, **params)

    def followed_all(self, *, bookmark_id: int | str | None = None, limit: int = 50,
                     max_pages: int = 100) -> list[dict[str, Any]]:
        """Every followed hole, paginated. Stops on the first non-full page (the
        standard signal); max_pages caps a runaway loop."""
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            holes = self.followed(bookmark_id=bookmark_id, page=page, limit=limit).get("list") or []
            out.extend(holes)
            if len(holes) < limit:  # partial or empty page → last page
                break
        return out

    def search(self, keyword: str, *, page: int = 1, limit: int = 25) -> dict[str, Any]:
        """One page of keyword search over all holes. Returns the raw {list, total}
        dict (same shape as `followed`).

        Search is `hole/list` + a `keyword` param, NOT a separate endpoint
        (verified live 2026-06; ~30 guessed dedicated routes all 404). It is
        SMS-gated like any content read, so a 40002 surfaces as
        NeedSMSVerification. A bare-digit keyword stays a keyword — it finds holes
        that quote/reference that number; for exact-id lookup use `hole(pid)`."""
        return self._get(endpoints.HOLE_LIST, keyword=keyword, page=page, limit=limit)

    def search_all(self, keyword: str, *, limit: int = 50,
                   max_pages: int = 20) -> list[dict[str, Any]]:
        """All hits for `keyword`, paginated on page fullness (never `total`; see
        followed). max_pages caps a runaway loop — kept lower than followed_all's
        cap because a keyword can match a great many holes."""
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            hits = self.search(keyword, page=page, limit=limit).get("list") or []
            out.extend(hits)
            if len(hits) < limit:  # partial or empty page → last page
                break
        return out

    def hole(self, pid: int | str) -> dict[str, Any]:
        return self._get(endpoints.HOLE_GET, pid=pid)

    def comments(self, pid: int | str, *, page: int = 1, limit: int = 25) -> list[dict[str, Any]]:
        data = self._get(endpoints.COMMENT_LIST, pid=pid, page=page, limit=limit)
        return data.get("list") or []

    def comments_all(self, pid: int | str, *, limit: int = 50,
                     max_pages: int = 200) -> list[dict[str, Any]]:
        """Full comment history for a hole, oldest-first. comment/list is
        oldest-first with ascending cid, so walk forward from page 1 until a
        non-full page (the last). Past-end pages return [] with code 20000, so
        this terminates; max_pages caps a runaway loop."""
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            cmts = self.comments(pid, page=page, limit=limit)
            out.extend(cmts)
            if len(cmts) < limit:  # partial or empty page → last page
                break
        return out

    # --- SMS verification -----------------------------------------------------
    def send_sms(self) -> None:
        """Trigger an SMS to the bound phone."""
        self._post(endpoints.SEND_SMS)

    def verify_sms(self, code: str) -> None:
        """Verify with the 4-digit code. Binds the verified state to this uuid."""
        self._post(endpoints.VERIFY_SMS, data={"valid_code": code})
