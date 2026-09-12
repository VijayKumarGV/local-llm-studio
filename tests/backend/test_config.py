"""Centralized config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import config


def test_defaults_present() -> None:
    c = config._load()
    assert c.bind_host == "127.0.0.1"
    assert c.bind_port == 8080
    assert c.ollama_host == "http://127.0.0.1:11434"
    assert c.log_level == "INFO"
    assert c.rate_limit_default == "120/minute"
    assert c.sandbox_image == "studio-sandbox:latest"
    assert c.allow_unsandboxed is False
    assert c.disable_keyring is False


def test_env_overrides_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("BIND_PORT", "9999")
    monkeypatch.setenv("OLLAMA_HOST", "http://remote:11434")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("STUDIO_RATE_LIMIT_DEFAULT", "5/second")
    monkeypatch.setenv("STUDIO_ALLOW_UNSANDBOXED", "1")
    c = config._load()
    assert c.bind_host == "0.0.0.0"
    assert c.bind_port == 9999
    assert c.ollama_host == "http://remote:11434"
    assert c.log_level == "DEBUG"
    assert c.rate_limit_default == "5/second"
    assert c.allow_unsandboxed is True


def test_data_dir_is_created_on_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "data"
    monkeypatch.setenv("STUDIO_DATA_DIR", str(target))
    config._load()
    assert target.exists() and target.is_dir()


def test_path_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_DB_PATH", "~/x/some.db")
    c = config._load()
    assert str(c.db_path).startswith(str(Path.home()))


def test_bool_parsing_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("STUDIO_ALLOW_UNSANDBOXED", truthy)
        assert config._load().allow_unsandboxed is True
    for falsy in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("STUDIO_ALLOW_UNSANDBOXED", falsy)
        assert config._load().allow_unsandboxed is False


def test_reload_updates_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    original_host = config.CONFIG.ollama_host
    monkeypatch.setenv("OLLAMA_HOST", "http://reloaded:11434")
    fresh = config.reload()
    assert fresh.ollama_host == "http://reloaded:11434"
    assert config.CONFIG.ollama_host == "http://reloaded:11434"
    # Reset for other tests
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    config.reload()
    assert config.CONFIG.ollama_host == original_host
