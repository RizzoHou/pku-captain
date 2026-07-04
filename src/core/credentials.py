"""CredentialStore — one place that owns the on-disk ``secrets/`` layout.

Historically every tool read (and, for treehole, wrote) its own files under
``secrets/<area>/`` ad-hoc, and the GUI had three unrelated login entry points:
treehole IAAA+SMS buried in the messages dialog, a P-Lib dialog that validated
but never persisted, and no API-key entry at all. This store centralises the
*writes*, *status* and *clears* the universal login page
(``src/ui/login_dialog.py``) needs, while the tools keep reading the same files
(the vendored treehole/plib libs resolve their own creds from disk). It is
deliberately dumb file I/O — no network, no SMS (that stays in
``TreeholeAuthService``).

Two credential kinds live here:

* **Accounts** — P-Lib ``email``/``password`` (now persisted), treehole
  presence/clear (the SMS *login* itself stays in ``TreeholeAuthService``, but
  logout/status route through here), and PKU ``id``/``password`` (the IAAA
  identity the pku3b client reads; mirrored from the treehole login since it is
  the same identity).
* **Models** — the chat brains, reframed as two configurable *roles* rather
  than two hard-coded brands. ``text`` (default DeepSeek) and ``visual``
  (default Kimi, vision-capable) each carry an ``api_key`` + ``base_url`` +
  ``model``, stored in ``secrets/models.json``. A user can point either role
  at any OpenAI-compatible endpoint; DeepSeek/Kimi are only the defaults. The
  legacy ``secrets/api_keys/<brand>_key.txt`` files are honoured as an
  ``api_key`` fallback so existing checkouts keep working with no migration.

Plus one piece of per-machine network config in the same tree (not a
credential, but the store stays the single ``secrets/`` writer): the proxy
mode + URL for ``src.core.network.apply_proxy``, in ``secrets/network.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .network import PROXY_MODES, ProxyConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The two model roles, in display order. `text` is the default chat brain.
MODEL_ROLES: tuple[str, ...] = ("text", "visual")

# Per-role storage defaults: the endpoint/model a role falls back to when the
# user has not customised it, plus the legacy single-key files (relative to
# `secrets/`) that seed the api_key for pre-existing checkouts.
_MODEL_DEFAULTS: dict[str, dict[str, object]] = {
    "text": {
        "label": "文本模型",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "legacy_keys": ("api_keys/deepseek_key.txt", "deepseek_key.txt"),
    },
    "visual": {
        "label": "视觉模型",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.6",
        "legacy_keys": ("api_keys/kimi_key.txt", "kimi_key.txt"),
    },
}


@dataclass(frozen=True)
class ModelConfig:
    """Resolved configuration for one model role (saved values over defaults)."""

    role: str
    label: str
    api_key: str
    base_url: str
    model: str

    @property
    def is_configured(self) -> bool:
        """A role is usable once it has an API key (endpoint/model always
        default). Presence of the key is what gates the brain being offered."""
        return bool(self.api_key)


def model_default(role: str, field: str) -> str:
    """Return a role's default `base_url` / `model` / `label` (for prefill)."""
    return str(_MODEL_DEFAULTS[role][field])


class CredentialStore:
    """Central reader/writer for the ``secrets/`` tree.

    Pure file I/O over a configurable ``secrets_dir`` (defaults to the repo
    root's ``secrets/``); tests point it at a tmp dir. Every write creates its
    parent directory, so a fresh install with an empty ``secrets/`` works.
    """

    def __init__(self, secrets_dir: str | Path | None = None) -> None:
        self.secrets_dir = (
            Path(secrets_dir) if secrets_dir is not None else _REPO_ROOT / "secrets"
        )
        self.treehole_dir = self.secrets_dir / "treehole"
        self.plib_dir = self.secrets_dir / "plib"
        self.pku_dir = self.secrets_dir / "pku"
        self.models_path = self.secrets_dir / "models.json"
        self.network_path = self.secrets_dir / "network.json"

    # -- small helpers ----------------------------------------------------
    @staticmethod
    def _read(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _write(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    # -- treehole (IAAA) --------------------------------------------------
    def has_treehole(self) -> bool:
        """True once id + password have been stored (login done at least once).

        The SMS-verified session lives in ``session.json``, written by
        ``TreeholeAuthService``; presence of id+password is the "an account is
        configured" signal the login page shows.
        """
        return bool(self._read(self.treehole_dir / "id")) and bool(
            self._read(self.treehole_dir / "password")
        )

    def clear_treehole(self) -> None:
        """Log out of treehole: drop credentials + cached session/state."""
        for name in ("id", "password", "session.json", "state.json"):
            path = self.treehole_dir / name
            if path.exists():
                path.unlink()

    # -- P-Lib ------------------------------------------------------------
    def plib(self) -> tuple[str, str] | None:
        """Stored ``(email, password)``, or None when either is absent."""
        email = self._read(self.plib_dir / "email")
        password = self._read(self.plib_dir / "password")
        if email and password:
            return email, password
        return None

    def has_plib(self) -> bool:
        return self.plib() is not None

    def save_plib(self, email: str, password: str) -> None:
        """Persist P-Lib credentials so every later call self-authenticates.

        The old ``PLibLoginDialog`` only validated (warmed the cookie jar) and
        never wrote these, so login did not survive a restart — this closes
        that gap.
        """
        self._write(self.plib_dir / "email", email.strip())
        self._write(self.plib_dir / "password", password)

    def clear_plib(self) -> None:
        for name in ("email", "password", "id"):
            path = self.plib_dir / name
            if path.exists():
                path.unlink()

    # -- PKU (pku3b / IAAA) -----------------------------------------------
    def pku(self) -> tuple[str, str] | None:
        """Stored IAAA ``(id, password)`` for the pku3b client, or None."""
        uid = self._read(self.pku_dir / "id")
        password = self._read(self.pku_dir / "password")
        if uid and password:
            return uid, password
        return None

    def has_pku(self) -> bool:
        return self.pku() is not None

    def save_pku(self, uid: str, password: str) -> None:
        """Persist IAAA credentials for the in-process ``pypku3b`` client.

        This is the *same* IAAA identity (学号 + 门户密码) the treehole tab logs
        in with, so the 统一身份 tab mirrors it here on a successful login — one
        login then provisions the pku3b tools (作业/公告/课表/身份), which read
        ``secrets/pku/{id,password}`` via ``stored_credentials``. Before this,
        those files had to be hand-placed per ``docs/setup_zh.md``.
        """
        self._write(self.pku_dir / "id", uid.strip())
        self._write(self.pku_dir / "password", password)

    def clear_pku(self) -> None:
        """Forget IAAA creds + the cached portal cookie jar (force re-login)."""
        for name in ("id", "password", "cookies.json"):
            path = self.pku_dir / name
            if path.exists():
                path.unlink()

    # -- network proxy ------------------------------------------------------
    def proxy(self) -> ProxyConfig:
        """The saved proxy setting; any unreadable/unknown state → default
        (`system`), so a corrupt file degrades to today's behavior."""
        if not self.network_path.exists():
            return ProxyConfig()
        try:
            raw = json.loads(self.network_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ProxyConfig()
        if not isinstance(raw, dict):
            return ProxyConfig()
        mode = str(raw.get("mode") or "")
        if mode not in PROXY_MODES:
            return ProxyConfig()
        url = str(raw.get("url") or "").strip()
        if mode == "manual" and not url:
            # A hand-edited manual entry with no URL would make apply_proxy
            # raise inside build_agent; degrade like any other corrupt state.
            return ProxyConfig()
        return ProxyConfig(mode=mode, url=url)

    def save_proxy(self, config: ProxyConfig) -> None:
        """Persist the 网络代理 tab's choice into ``secrets/network.json``."""
        if config.mode not in PROXY_MODES:
            raise ValueError(f"unknown proxy mode: {config.mode!r}")
        self.network_path.parent.mkdir(parents=True, exist_ok=True)
        self.network_path.write_text(
            json.dumps(
                {"mode": config.mode, "url": config.url.strip()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- models -----------------------------------------------------------
    def _load_models(self) -> dict[str, dict[str, str]]:
        if not self.models_path.exists():
            return {}
        try:
            raw = json.loads(self.models_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            role: value
            for role, value in raw.items()
            if role in _MODEL_DEFAULTS and isinstance(value, dict)
        }

    def _legacy_key(self, role: str) -> str:
        """First non-empty legacy ``secrets/<...>_key.txt`` for a role, else ''."""
        for rel in _MODEL_DEFAULTS[role]["legacy_keys"]:  # type: ignore[union-attr]
            value = self._read(self.secrets_dir / rel)
            if value:
                return value
        return ""

    def model(self, role: str) -> ModelConfig:
        """Resolve a role: saved values over defaults, api_key over legacy key."""
        if role not in _MODEL_DEFAULTS:
            raise ValueError(f"unknown model role: {role!r}")
        defaults = _MODEL_DEFAULTS[role]
        saved = self._load_models().get(role, {})
        api_key = str(saved.get("api_key") or "").strip() or self._legacy_key(role)
        base_url = str(saved.get("base_url") or "").strip() or str(defaults["base_url"])
        model = str(saved.get("model") or "").strip() or str(defaults["model"])
        return ModelConfig(
            role=role,
            label=str(defaults["label"]),
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    def is_model_configured(self, role: str) -> bool:
        return self.model(role).is_configured

    def save_model(
        self, role: str, *, api_key: str, base_url: str = "", model: str = ""
    ) -> None:
        """Persist a role's endpoint/model/key into ``secrets/models.json``.

        Empty ``base_url`` / ``model`` fall back to the role defaults so the
        saved record is always complete; the caller (login page) prefills the
        fields with the defaults, so a blank means "use default".
        """
        if role not in _MODEL_DEFAULTS:
            raise ValueError(f"unknown model role: {role!r}")
        data = self._load_models()
        data[role] = {
            "api_key": api_key.strip(),
            "base_url": base_url.strip() or model_default(role, "base_url"),
            "model": model.strip() or model_default(role, "model"),
        }
        self.models_path.parent.mkdir(parents=True, exist_ok=True)
        self.models_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def clear_model(self, role: str) -> None:
        """Forget a role's saved config (reverting to defaults + legacy key)."""
        data = self._load_models()
        if data.pop(role, None) is not None:
            self.models_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
