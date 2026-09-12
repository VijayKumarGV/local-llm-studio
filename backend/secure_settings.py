"""Sensitive settings via macOS Keychain (or any `keyring`-supported backend).

Everything the user has to keep private — third-party API keys mostly —
lives in Keychain. Non-sensitive settings stay in the SQLite settings
table as before.

The allowlist below is authoritative: only keys in `_SENSITIVE` are
routed through Keychain. Anything else raises to prevent accidental
promotion of unintended data.

Public API:
    * get_secret(key)  → str | None
    * set_secret(key, value)
    * delete_secret(key)
    * is_sensitive(key)  → bool
    * merge_into(settings) → dict[str, str]
        Returns the settings dict with sensitive keys overlaid from
        Keychain. Used by database.get_settings.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

from backend.config import CONFIG

log = logging.getLogger("studio.secure_settings")

SERVICE = "LocalLLMStudio"

_SENSITIVE = frozenset(
    {
        "tavily_api_key",
        "brave_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "google_search_api_key",
        "google_search_cx",
    }
)


def is_sensitive(key: str) -> bool:
    return key in _SENSITIVE


def _kr() -> Any:
    """Import lazily so the module still loads when `keyring` isn't
    available (dev sandboxes, some CI). Returns None on any failure."""
    try:
        import keyring

        return keyring
    except Exception as e:  # pragma: no cover — depends on env
        log.warning("keyring unavailable: %s", e)
        return None


def get_secret(key: str) -> str | None:
    if not is_sensitive(key):
        raise ValueError(f"{key!r} is not in the sensitive-key allowlist")
    if os.environ.get("STUDIO_DISABLE_KEYRING") or CONFIG.disable_keyring:
        return None
    kr = _kr()
    if kr is None:
        return None
    with contextlib.suppress(Exception):
        return kr.get_password(SERVICE, key)
    return None


def set_secret(key: str, value: str) -> None:
    if not is_sensitive(key):
        raise ValueError(f"{key!r} is not in the sensitive-key allowlist")
    kr = _kr()
    if kr is None:
        raise RuntimeError("keyring backend unavailable")
    kr.set_password(SERVICE, key, value)


def delete_secret(key: str) -> None:
    if not is_sensitive(key):
        raise ValueError(f"{key!r} is not in the sensitive-key allowlist")
    kr = _kr()
    if kr is None:
        return
    with contextlib.suppress(Exception):
        kr.delete_password(SERVICE, key)


def merge_into(settings: dict[str, str]) -> dict[str, str]:
    """Overlay Keychain values on top of a plain settings dict. Keys the
    Keychain doesn't have are left untouched. Non-sensitive keys never
    touched."""
    if os.environ.get("STUDIO_DISABLE_KEYRING") or CONFIG.disable_keyring:
        return settings
    out = dict(settings)
    for key in _SENSITIVE:
        val = get_secret(key)
        if val is not None:
            out[key] = val
    return out
