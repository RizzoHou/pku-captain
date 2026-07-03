"""The public in-process client facade.

Ties the cookie-bearing :class:`HttpClient`, the TTL :class:`Cache`, and the
Blackboard/portal sub-clients together behind four methods that mirror the used
pku3b commands. Credentials are resolved lazily so an offline/no-secrets host can
still import the package; a fresh :class:`Client` per call keeps no shared mutable
state (safe to build inside a Tool per invocation, like ``PlibClient``).
"""

from __future__ import annotations

from pathlib import Path

from .blackboard import BlackboardClient
from .cache import Cache
from .config import Credentials, default_cookie_path, load_credentials
from .errors import ConfigError
from .http import HttpClient
from .models import Announcement, Assignment, CourseTable, Identity
from .portal import PortalClient


def _default_cache_dir() -> Path:
    return Path.home() / ".cache" / "pypku3b" / "crawl"


class Client:
    def __init__(
        self,
        *,
        credentials: Credentials | None = None,
        secrets_dir: Path | str | None = None,
        timeout: float = 60.0,
        cookie_path: Path | str | None = None,
        seed_cookie_path: Path | str | None = None,
        cache_dir: Path | str | None = "__default__",
        cache_ttl: float = 3600.0,
        workers: int = 8,
        verify: str | bool | None = None,
    ) -> None:
        self._credentials = credentials
        self._secrets_dir = secrets_dir
        self.timeout = timeout
        self.workers = workers
        self.verify = verify
        self.cookie_path = (
            Path(cookie_path) if cookie_path is not None else default_cookie_path()
        )
        self.seed_cookie_path = seed_cookie_path
        if cache_dir == "__default__":
            cache_dir = _default_cache_dir()
        self._cache = Cache(cache_dir, default_ttl=cache_ttl)
        self._http_client: HttpClient | None = None

    # -- wiring -------------------------------------------------------------

    def _creds(self) -> Credentials:
        if self._credentials is not None:
            return self._credentials
        resolved = load_credentials(self._secrets_dir)
        if resolved is None:
            raise ConfigError(
                "no PKU credentials found (set secrets/pku/{id,password} or "
                "PKU_USERNAME/PKU_PASSWORD)"
            )
        self._credentials = resolved
        return resolved

    def _http(self) -> HttpClient:
        if self._http_client is None:
            self._http_client = HttpClient(
                timeout=self.timeout,
                cookie_path=self.cookie_path,
                seed_cookie_path=self.seed_cookie_path,
                verify=self.verify,
            )
        return self._http_client

    def _blackboard(self) -> BlackboardClient:
        return BlackboardClient(self._http(), self._cache, workers=self.workers)

    def _portal(self) -> PortalClient:
        return PortalClient(self._http())

    # -- public API ---------------------------------------------------------

    def list_assignments(
        self,
        *,
        include_completed: bool = False,
        all_term: bool = False,
        force: bool = False,
        otp_code: str = "",
    ) -> list[Assignment]:
        bb = self._blackboard()
        bb.login(self._creds(), otp_code)
        return bb.list_assignments(
            include_completed=include_completed or all_term,
            only_current=not all_term,
            force=force,
        )

    def list_announcements(
        self,
        *,
        all_term: bool = False,
        force: bool = False,
        otp_code: str = "",
    ) -> list[Announcement]:
        bb = self._blackboard()
        bb.login(self._creds(), otp_code)
        return bb.list_announcements(only_current=not all_term, force=force)

    def get_identity(self, *, otp_code: str = "") -> Identity:
        identity = self._portal().get_identity(self._creds(), otp_code)
        self._http().save_cookies()
        return identity

    def get_coursetable(
        self, *, force: bool = False, otp_code: str = ""
    ) -> CourseTable:
        # `force` is accepted for CLI/API parity; the portal is not memoized
        # (login is per-call), so it currently has no cache to bypass.
        table = self._portal().get_coursetable(self._creds(), otp_code)
        self._http().save_cookies()
        return table
