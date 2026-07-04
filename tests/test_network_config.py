"""Proxy config — store round-trip + process-env application.

Hermetic: tmp secrets dirs, and every apply test snapshots/restores the
managed env vars plus resets the module's first-apply snapshot, so no proxy
state leaks between tests (or into the rest of the suite).
"""

from __future__ import annotations

import os

import pytest
import requests.utils

from src.core import bootstrap, network
from src.core.credentials import CredentialStore
from src.core.network import ProxyConfig, apply_proxy, normalize_proxy_url


@pytest.fixture
def proxy_env(monkeypatch):
    saved = {name: os.environ.get(name) for name in network._MANAGED_VARS}
    for name in network._MANAGED_VARS:
        os.environ.pop(name, None)
    monkeypatch.setattr(network, "_original_env", None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# -- store round-trip -------------------------------------------------------


def test_default_is_system(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    assert store.proxy() == ProxyConfig(mode="system", url="")


def test_save_and_read_back(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_proxy(ProxyConfig(mode="manual", url="http://127.0.0.1:7890"))
    assert store.proxy() == ProxyConfig(mode="manual", url="http://127.0.0.1:7890")


def test_url_survives_non_manual_mode(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_proxy(ProxyConfig(mode="direct", url="http://127.0.0.1:7890"))
    assert store.proxy() == ProxyConfig(mode="direct", url="http://127.0.0.1:7890")


def test_corrupt_file_falls_back_to_system(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.network_path.parent.mkdir(parents=True)
    store.network_path.write_text("{not json", encoding="utf-8")
    assert store.proxy() == ProxyConfig()


def test_unknown_mode_falls_back_to_system(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.network_path.parent.mkdir(parents=True)
    store.network_path.write_text('{"mode": "socks-rocket"}', encoding="utf-8")
    assert store.proxy() == ProxyConfig()


def test_save_rejects_unknown_mode(tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    with pytest.raises(ValueError):
        store.save_proxy(ProxyConfig(mode="socks-rocket"))


# -- URL normalisation --------------------------------------------------------


def test_normalize_adds_default_scheme() -> None:
    assert normalize_proxy_url(" 127.0.0.1:7890 ") == "http://127.0.0.1:7890"
    assert normalize_proxy_url("socks5://127.0.0.1:7891") == "socks5://127.0.0.1:7891"
    assert normalize_proxy_url("   ") == ""


# -- env application ----------------------------------------------------------


def test_manual_sets_proxy_vars(proxy_env) -> None:
    apply_proxy(ProxyConfig(mode="manual", url="127.0.0.1:7890"))
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        assert os.environ[name] == "http://127.0.0.1:7890"
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"


def test_manual_requires_url(proxy_env) -> None:
    with pytest.raises(ValueError):
        apply_proxy(ProxyConfig(mode="manual", url="  "))


def test_direct_clears_and_bypasses(proxy_env) -> None:
    os.environ["HTTPS_PROXY"] = "http://10.0.0.1:8080"  # e.g. inherited from shell
    apply_proxy(ProxyConfig(mode="direct"))
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["NO_PROXY"] == "*"
    assert os.environ["no_proxy"] == "*"
    # The macOS decoy that keeps urllib on the (empty) env instead of falling
    # back to the SystemConfiguration proxies.
    assert os.environ[network._DECOY_VAR] == network._DECOY_URL


def test_system_restores_the_original_env(proxy_env) -> None:
    os.environ["https_proxy"] = "http://10.0.0.1:8080"
    apply_proxy(ProxyConfig(mode="manual", url="http://127.0.0.1:7890"))
    apply_proxy(ProxyConfig(mode="system"))
    assert os.environ["https_proxy"] == "http://10.0.0.1:8080"
    assert "NO_PROXY" not in os.environ
    assert network._DECOY_VAR not in os.environ


def test_apply_rejects_unknown_mode(proxy_env) -> None:
    with pytest.raises(ValueError):
        apply_proxy(ProxyConfig(mode="socks-rocket"))


def test_requests_honours_the_modes(proxy_env) -> None:
    """Pin the exact `requests` behavior the whole feature stands on."""
    url = "https://course.pku.edu.cn/webapps/portal"
    apply_proxy(ProxyConfig(mode="manual", url="http://127.0.0.1:7890"))
    assert requests.utils.get_environ_proxies(url)["https"] == "http://127.0.0.1:7890"
    apply_proxy(ProxyConfig(mode="direct"))
    assert requests.utils.get_environ_proxies(url) == {}


# -- bootstrap wiring ----------------------------------------------------------


def test_build_agent_applies_saved_proxy(proxy_env, monkeypatch, tmp_path) -> None:
    store = CredentialStore(tmp_path / "secrets")
    store.save_proxy(ProxyConfig(mode="manual", url="http://127.0.0.1:7890"))
    monkeypatch.setattr(bootstrap, "_store", lambda: store)
    bootstrap.build_agent(offline=True)
    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"
