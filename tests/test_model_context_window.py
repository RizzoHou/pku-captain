"""User-configurable per-role context window.

Covers the full seam: `CredentialStore.save_model`/`model` round-trip of the new
`context_window` field, back-compat with old 3-field records, and that
`bootstrap._build_role_provider` threads the value onto the live provider as an
instance attribute that shadows the ClassVar (blank ⇒ ClassVar default).
"""

from __future__ import annotations

import json

from src.core.bootstrap import _build_role_provider
from src.core.credentials import CredentialStore, ModelConfig


def _store(tmp_path) -> CredentialStore:
    return CredentialStore(tmp_path / "secrets")


def _cfg(**overrides) -> ModelConfig:
    base = dict(
        role="text",
        label="文本模型",
        api_key="k",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        context_window=None,
    )
    base.update(overrides)
    return ModelConfig(**base)  # type: ignore[arg-type]


# -- credentials round-trip ------------------------------------------------
def test_save_and_read_back_context_window(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model("text", api_key="k", context_window=500_000)
    cfg = CredentialStore(tmp_path / "secrets").model("text")  # fresh instance
    assert cfg.context_window == 500_000


def test_blank_context_window_is_none(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model("text", api_key="k")  # no context_window given
    assert store.model("text").context_window is None
    # Explicit None / zero / negative all coerce to unset (omitted from JSON).
    store.save_model("visual", api_key="k", context_window=0)
    assert store.model("visual").context_window is None
    raw = json.loads((tmp_path / "secrets" / "models.json").read_text())
    assert "context_window" not in raw["text"]
    assert "context_window" not in raw["visual"]


def test_positive_window_is_persisted_in_json(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model("text", api_key="k", context_window=128_000)
    raw = json.loads((tmp_path / "secrets" / "models.json").read_text())
    assert raw["text"]["context_window"] == 128_000


def test_backcompat_old_three_field_record_loads(tmp_path) -> None:
    """An existing models.json without `context_window` must still parse."""
    store = _store(tmp_path)
    store.models_path.parent.mkdir(parents=True)
    store.models_path.write_text(
        json.dumps(
            {
                "text": {
                    "api_key": "old-key",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-v4-pro",
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = store.model("text")
    assert cfg.api_key == "old-key"
    assert cfg.context_window is None  # absent ⇒ provider default in force


def test_string_window_in_json_is_coerced(tmp_path) -> None:
    """A hand-edited string value coerces like the GUI field would."""
    store = _store(tmp_path)
    store.models_path.parent.mkdir(parents=True)
    store.models_path.write_text(
        json.dumps({"text": {"api_key": "k", "context_window": "750000"}}),
        encoding="utf-8",
    )
    assert store.model("text").context_window == 750_000


# -- provider threading ----------------------------------------------------
def test_deepseek_provider_honors_configured_window() -> None:
    llm = _build_role_provider(_cfg(context_window=500_000), "deepseek")
    assert llm.context_window == 500_000


def test_deepseek_provider_defaults_to_classvar_when_unset() -> None:
    llm = _build_role_provider(_cfg(context_window=None), "deepseek")
    assert llm.context_window == 1_000_000  # DeepSeek V4 ClassVar default


def test_kimi_provider_honors_configured_window() -> None:
    cfg = _cfg(role="visual", model="kimi-k2.6", context_window=300_000)
    assert _build_role_provider(cfg, "kimi").context_window == 300_000


def test_kimi_provider_defaults_to_classvar_when_unset() -> None:
    cfg = _cfg(role="visual", model="kimi-k2.6", context_window=None)
    assert _build_role_provider(cfg, "kimi").context_window == 256_000
