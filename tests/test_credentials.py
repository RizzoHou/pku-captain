"""CredentialStore — the central reader/writer for the secrets/ tree.

Covers model-role resolution (defaults, legacy-key fallback, custom endpoint,
persist/clear) plus the P-Lib and treehole account read/write/clear paths. All
against a tmp secrets dir — no real credentials touched.
"""

from __future__ import annotations

import json

from src.core.credentials import CredentialStore, model_default


def _store(tmp_path) -> CredentialStore:
    return CredentialStore(tmp_path / "secrets")


# -- models ---------------------------------------------------------------
def test_model_defaults_when_nothing_saved(tmp_path) -> None:
    store = _store(tmp_path)
    text = store.model("text")
    assert text.base_url == model_default("text", "base_url")
    assert text.model == "deepseek-v4-pro"
    assert text.api_key == ""  # no key yet
    assert not text.is_configured
    assert store.model("visual").model == "kimi-k2.6"


def test_legacy_key_file_seeds_api_key(tmp_path) -> None:
    store = _store(tmp_path)
    legacy = tmp_path / "secrets" / "api_keys" / "deepseek_key.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-deepseek", encoding="utf-8")
    cfg = store.model("text")
    assert cfg.api_key == "legacy-deepseek"
    assert cfg.is_configured
    assert store.is_model_configured("text")


def test_flat_legacy_key_fallback(tmp_path) -> None:
    store = _store(tmp_path)
    flat = tmp_path / "secrets" / "kimi_key.txt"
    flat.parent.mkdir(parents=True)
    flat.write_text("flat-kimi", encoding="utf-8")
    assert store.model("visual").api_key == "flat-kimi"


def test_save_model_persists_and_reads_back(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model(
        "text",
        api_key=" my-key ",
        base_url="https://proxy.example.com/v1",
        model="custom-model",
    )
    cfg = CredentialStore(tmp_path / "secrets").model("text")  # fresh instance
    assert cfg.api_key == "my-key"  # trimmed
    assert cfg.base_url == "https://proxy.example.com/v1"
    assert cfg.model == "custom-model"


def test_save_model_blank_fields_fall_back_to_defaults(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model("visual", api_key="k", base_url="", model="")
    cfg = store.model("visual")
    assert cfg.base_url == model_default("visual", "base_url")
    assert cfg.model == model_default("visual", "model")


def test_saved_key_wins_over_legacy(tmp_path) -> None:
    store = _store(tmp_path)
    legacy = tmp_path / "secrets" / "api_keys" / "deepseek_key.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    store.save_model("text", api_key="explicit")
    assert store.model("text").api_key == "explicit"


def test_clear_model_reverts_to_legacy(tmp_path) -> None:
    store = _store(tmp_path)
    legacy = tmp_path / "secrets" / "api_keys" / "deepseek_key.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    store.save_model("text", api_key="explicit", model="x")
    store.clear_model("text")
    cfg = store.model("text")
    assert cfg.api_key == "legacy"
    assert cfg.model == "deepseek-v4-pro"  # back to default


def test_models_json_is_valid_json(tmp_path) -> None:
    store = _store(tmp_path)
    store.save_model("text", api_key="a")
    store.save_model("visual", api_key="b")
    raw = json.loads((tmp_path / "secrets" / "models.json").read_text())
    assert set(raw) == {"text", "visual"}
    assert raw["text"]["api_key"] == "a"


def test_corrupt_models_json_is_ignored(tmp_path) -> None:
    store = _store(tmp_path)
    store.models_path.parent.mkdir(parents=True)
    store.models_path.write_text("{ not json", encoding="utf-8")
    assert store.model("text").model == "deepseek-v4-pro"  # falls back, no raise


# -- P-Lib ----------------------------------------------------------------
def test_plib_save_read_clear(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.plib() is None
    assert not store.has_plib()
    store.save_plib(" user@pku.edu.cn ", "pw")
    assert store.plib() == ("user@pku.edu.cn", "pw")  # email trimmed
    assert store.has_plib()
    store.clear_plib()
    assert store.plib() is None


# -- PKU (pku3b / IAAA) ---------------------------------------------------
def test_pku_save_read_clear(tmp_path) -> None:
    store = _store(tmp_path)
    assert store.pku() is None
    assert not store.has_pku()
    store.save_pku(" 2500013225 ", "pw")
    assert store.pku() == ("2500013225", "pw")  # id trimmed
    assert store.has_pku()
    # A cached portal cookie jar is dropped on clear so the next login re-auths.
    (store.pku_dir / "cookies.json").write_text("{}", encoding="utf-8")
    store.clear_pku()
    assert store.pku() is None
    assert not (store.pku_dir / "cookies.json").exists()


# -- treehole -------------------------------------------------------------
def test_treehole_presence_and_clear(tmp_path) -> None:
    store = _store(tmp_path)
    assert not store.has_treehole()
    store.treehole_dir.mkdir(parents=True)
    (store.treehole_dir / "id").write_text("2500013225", encoding="utf-8")
    (store.treehole_dir / "password").write_text("pw", encoding="utf-8")
    (store.treehole_dir / "session.json").write_text("{}", encoding="utf-8")
    assert store.has_treehole()
    store.clear_treehole()
    assert not store.has_treehole()
    assert not (store.treehole_dir / "session.json").exists()
