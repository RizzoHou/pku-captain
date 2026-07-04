"""Process-wide proxy control — one switch for every network touch.

The app's network I/O is spread across code we own (`DeepSeekProvider` /
`KimiProvider`) and vendored libraries we must not edit (`pypku3b`,
`plib_cli`, `treehole`, `dean`). All of it runs on `requests` with default
``trust_env=True`` and none of it sets its own proxies, so the one lever that
governs *everything* — vendor included — is the process environment
(``HTTP_PROXY`` / ``HTTPS_PROXY``). `requests` re-reads those per request
(``Session.merge_environment_settings``), so a change takes effect on the very
next call with no restart and no session rebuild.

Three modes (persisted by ``CredentialStore.save_proxy`` in
``secrets/network.json``, edited in the 账号中心 网络代理 tab):

* ``system`` — leave the environment alone (whatever the shell / OS provides).
  This is today's behavior and the default.
* ``direct`` — ignore proxies entirely, *including the macOS system proxy*.
  Deleting the env vars is not enough on macOS: with an empty proxy
  environment, urllib falls back to the SystemConfiguration framework
  (``getproxies_macosx_sysconf``), so a system-level Clash/mihomo still
  captures the app. We therefore also plant a decoy ``gopher_proxy`` entry:
  a non-empty ``getproxies_environment()`` makes urllib treat the environment
  as the authoritative proxy source (empty for http/https) and routes
  ``proxy_bypass`` through ``proxy_bypass_environment``, which honours
  ``no_proxy="*"``. The gopher scheme is never requested, so the decoy value
  is inert.
* ``manual`` — send all http/https traffic through one user-given proxy URL
  (e.g. a local mihomo at ``http://127.0.0.1:7890``), regardless of what the
  OS thinks.

The first `apply_proxy` call snapshots the managed env vars so a later switch
back to ``system`` restores the process's original environment exactly.

Known limit: env vars only cover *this* process (and its children). The macOS
treehole LaunchAgent notifier is a separate daemon and keeps its own network
path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PROXY_MODES: tuple[str, ...] = ("system", "direct", "manual")

# What the 网络代理 tab prefills for manual mode — the conventional local
# Clash/mihomo HTTP port.
DEFAULT_PROXY_URL = "http://127.0.0.1:7890"

# Both cases: getproxies_environment() checks lowercase first, but plenty of
# tools read only the uppercase spelling.
_HTTP_VARS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")
_ALL_VARS = ("ALL_PROXY", "all_proxy")
_BYPASS_VARS = ("NO_PROXY", "no_proxy")
# The macOS decoy for direct mode (see module docstring). Port 9 is discard;
# the value only needs to exist, never to work.
_DECOY_VAR = "gopher_proxy"
_DECOY_URL = "http://127.0.0.1:9"

_MANAGED_VARS: tuple[str, ...] = (*_HTTP_VARS, *_ALL_VARS, *_BYPASS_VARS, _DECOY_VAR)

# Snapshot of the managed vars as they were before the first apply_proxy(),
# so `system` mode can restore the untouched environment.
_original_env: dict[str, str | None] | None = None


@dataclass(frozen=True)
class ProxyConfig:
    """One proxy decision: a mode plus the manual-mode URL.

    ``url`` is kept even while the mode is `system`/`direct` so the GUI can
    remember the last manual address; only `manual` mode ever uses it.
    """

    mode: str = "system"
    url: str = ""


def normalize_proxy_url(url: str) -> str:
    """Trim and default the scheme (`127.0.0.1:7890` → `http://127.0.0.1:7890`)."""
    url = url.strip()
    if url and "://" not in url:
        url = f"http://{url}"
    return url


def apply_proxy(config: ProxyConfig) -> None:
    """Point the process environment at the configured proxy mode.

    Idempotent and cheap; callers re-apply freely (bootstrap at startup, the
    账号中心 tab on save). Requests made after this call follow the new mode.
    """
    global _original_env
    if _original_env is None:
        _original_env = {name: os.environ.get(name) for name in _MANAGED_VARS}

    if config.mode == "system":
        for name, value in _original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return

    for name in _MANAGED_VARS:
        os.environ.pop(name, None)

    if config.mode == "direct":
        for name in _BYPASS_VARS:
            os.environ[name] = "*"
        os.environ[_DECOY_VAR] = _DECOY_URL
        return

    if config.mode == "manual":
        url = normalize_proxy_url(config.url)
        if not url:
            raise ValueError("manual proxy mode requires a proxy URL")
        for name in _HTTP_VARS:
            os.environ[name] = url
        # Never proxy loopback — the proxy itself lives there.
        for name in _BYPASS_VARS:
            os.environ[name] = "localhost,127.0.0.1"
        return

    raise ValueError(f"unknown proxy mode: {config.mode!r}")
