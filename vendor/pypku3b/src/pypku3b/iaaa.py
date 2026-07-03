"""IAAA single-sign-on primitives shared by every login flow.

Two endpoints drive all logins (Blackboard, portalPublicQuery, portal2017);
the only per-app difference is the ``appid`` and the ``redirUrl``.
"""

from __future__ import annotations

import random

from .errors import AuthError, IAAALockout, NeedOTP, ParseError
from .http import HttpClient

IS_MOBILE_AUTHEN = "https://iaaa.pku.edu.cn/iaaa/isMobileAuthen.do"
OAUTH_LOGIN = "https://iaaa.pku.edu.cn/iaaa/oauthlogin.do"


def _rand() -> str:
    """A random float in (0, 1) formatted like Rust's ``{:.20}`` ``_rand`` param."""
    # Value only needs to be a plausible cache-buster; exact bit-pattern is
    # irrelevant to the server.
    return f"{random.uniform(1e-20, 1.0):.20f}"


def is_mobile_authen(http: HttpClient, appid: str, username: str) -> dict:
    """GET ``isMobileAuthen.do`` and return the parsed JSON (``AuthenData``)."""
    res = http.get(
        IS_MOBILE_AUTHEN,
        params={"appId": appid, "userName": username, "_rand": _rand()},
    )
    try:
        return res.json()
    except ValueError as exc:
        raise ParseError(f"isMobileAuthen returned non-JSON for {appid}") from exc


def require_otp(http: HttpClient, appid: str, username: str) -> bool:
    """Whether *appid* login for *username* currently requires an OTP."""
    data = is_mobile_authen(http, appid, username)
    return str(data.get("authenMode")) == "OTP"


def oauth_login(
    http: HttpClient,
    *,
    appid: str,
    username: str,
    password: str,
    otp_code: str,
    redir: str,
) -> str:
    """POST ``oauthlogin.do`` and return the SSO token.

    Sends all seven form fields (including the empty ``randCode``/``smsCode``)
    in pku3b's exact order. Maps IAAA error codes: ``E05`` -> :class:`NeedOTP`,
    ``E21`` -> :class:`IAAALockout`, anything else -> :class:`AuthError`.
    """
    res = http.post(
        OAUTH_LOGIN,
        data=[
            ("appid", appid),
            ("userName", username),
            ("password", password),
            ("randCode", ""),
            ("smsCode", ""),
            ("otpCode", otp_code),
            ("redirUrl", redir),
        ],
    )
    if not res.ok:
        raise AuthError(f"oauth login HTTP {res.status_code} for {appid}")
    try:
        data = res.json()
    except ValueError as exc:
        raise ParseError("oauth login returned non-JSON") from exc

    if not data.get("success"):
        errors = data.get("errors") or {}
        code = str(errors.get("code") or "")
        msg = str(errors.get("msg") or "login failed")
        if code == "E05":
            raise NeedOTP(f"OTP incorrect [{code}]: {msg}")
        if code == "E21":
            raise IAAALockout(f"too many attempts [{code}]: {msg}")
        raise AuthError(f"oauth login failed [{code}]: {msg}")

    token = data.get("token")
    if not token:
        raise AuthError("oauth login succeeded but no token was returned")
    return str(token)
