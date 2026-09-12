"""Keychain-backed secret settings.

Tests use `keyring`'s in-memory backend so they don't touch the real
macOS Keychain — completely isolated + repeatable.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _in_memory_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in an in-memory keyring backend for the duration of each test."""
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryBackend(KeyringBackend):
        priority = 999.0  # type: ignore[assignment]

        def __init__(self) -> None:
            self._store: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self._store.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self._store[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            self._store.pop((service, username), None)

    backend = MemoryBackend()
    original = keyring.get_keyring()
    keyring.set_keyring(backend)
    monkeypatch.delenv("STUDIO_DISABLE_KEYRING", raising=False)
    yield
    keyring.set_keyring(original)


def test_is_sensitive_allowlist() -> None:
    from backend import secure_settings

    assert secure_settings.is_sensitive("openai_api_key") is True
    assert secure_settings.is_sensitive("tavily_api_key") is True
    assert secure_settings.is_sensitive("default_model") is False
    assert secure_settings.is_sensitive("some_random_key") is False


def test_set_and_get_secret_roundtrip() -> None:
    from backend import secure_settings

    secure_settings.set_secret("openai_api_key", "sk-test-abc")
    assert secure_settings.get_secret("openai_api_key") == "sk-test-abc"


def test_delete_secret() -> None:
    from backend import secure_settings

    secure_settings.set_secret("brave_api_key", "brave-tok")
    secure_settings.delete_secret("brave_api_key")
    assert secure_settings.get_secret("brave_api_key") is None


def test_non_sensitive_key_rejected_on_get() -> None:
    from backend import secure_settings

    with pytest.raises(ValueError):
        secure_settings.get_secret("default_model")


def test_non_sensitive_key_rejected_on_set() -> None:
    from backend import secure_settings

    with pytest.raises(ValueError):
        secure_settings.set_secret("default_model", "anything")


def test_missing_secret_returns_none() -> None:
    from backend import secure_settings

    assert secure_settings.get_secret("google_search_api_key") is None


def test_merge_into_overlays_secrets() -> None:
    from backend import secure_settings

    secure_settings.set_secret("openai_api_key", "sk-from-keychain")
    base = {"default_model": "qwen2.5:32b", "openai_api_key": "sk-stale-plaintext"}
    merged = secure_settings.merge_into(base)
    assert merged["openai_api_key"] == "sk-from-keychain"  # Keychain wins
    assert merged["default_model"] == "qwen2.5:32b"  # untouched


def test_merge_into_leaves_non_sensitive_alone() -> None:
    from backend import secure_settings

    base = {"default_model": "custom", "theme": "dark"}
    merged = secure_settings.merge_into(base)
    assert merged == base


def test_disable_keyring_env_short_circuits() -> None:
    import os

    from backend import secure_settings

    secure_settings.set_secret("tavily_api_key", "should-not-be-returned")
    os.environ["STUDIO_DISABLE_KEYRING"] = "1"
    try:
        assert secure_settings.get_secret("tavily_api_key") is None
        assert secure_settings.merge_into({"x": "y"}) == {"x": "y"}
    finally:
        del os.environ["STUDIO_DISABLE_KEYRING"]


def test_save_setting_routes_secret_to_keychain(fresh_schema: str) -> None:
    """database.save_setting must divert sensitive keys to Keychain and
    strip any stale plaintext from SQLite."""
    from backend import database, secure_settings

    # First write a plaintext row directly to prove the DELETE fires.
    with database.get_connection() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("openai_api_key", "stale-plaintext"))
        conn.commit()

    database.save_setting("openai_api_key", "sk-safe-in-keychain")

    # Plaintext row gone
    with database.get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", ("openai_api_key",)).fetchone()
        assert row is None

    # get_settings surfaces the Keychain value
    settings = database.get_settings()
    assert settings.get("openai_api_key") == "sk-safe-in-keychain"
    # Direct keychain lookup agrees
    assert secure_settings.get_secret("openai_api_key") == "sk-safe-in-keychain"


def test_save_setting_non_sensitive_still_writes_sqlite(fresh_schema: str) -> None:
    from backend import database

    database.save_setting("default_model", "my-custom-model:latest")
    assert database.get_settings().get("default_model") == "my-custom-model:latest"
