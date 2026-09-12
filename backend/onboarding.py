"""
First-run detection.

`GET /api/onboarding/status` returns a small JSON summary the frontend
uses to decide whether to show the setup wizard. Everything here is
best-effort: a failure to reach ollama returns ollama_up=false rather
than an HTTP error so the wizard can still render.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from backend import database
from backend.config import CONFIG
from backend.ollama_client import get_ollama_client

log = logging.getLogger("studio.onboarding")

# Kept small on purpose — this is what the wizard offers to install.
# Users can always pull more from Settings later.
RECOMMENDED_MODELS: tuple[str, ...] = (
    "nomic-embed-text",  # required for RAG
    "qwen2.5:32b",  # default chat model
    "qwen2.5-coder:32b",  # coding expert default
    "llama3.2:1b",  # routing / HyDE / triage
)


async def _installed_models(timeout: float = 3.0) -> list[str]:
    """Return the list of models Ollama reports. Empty list on error."""
    client = get_ollama_client()
    try:
        resp = await client.get("/api/tags", timeout=timeout)
        resp.raise_for_status()
    except (httpx.HTTPError, OSError) as e:
        log.info("onboarding: ollama /api/tags failed: %s", e)
        return []
    try:
        return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except (ValueError, AttributeError):
        return []


def _base_names(installed: list[str]) -> set[str]:
    """Ollama tags are `name:tag`; strip the tag so `qwen2.5:32b` matches
    the recommended entry even if the user has multiple sizes pulled."""
    return {name.split(":", 1)[0] for name in installed}


def _recommended_missing(installed: list[str]) -> list[str]:
    installed_full = set(installed)
    installed_base = _base_names(installed)
    missing: list[str] = []
    for rec in RECOMMENDED_MODELS:
        # Match either the exact tag or the base name (any tag).
        if rec in installed_full:
            continue
        if rec.split(":", 1)[0] in installed_base:
            continue
        missing.append(rec)
    return missing


def _workspaces_created() -> int:
    try:
        return len(database.list_projects())
    except Exception as e:
        log.info("onboarding: list_projects failed: %s", e)
        return 0


def _corpus_downloaded() -> bool:
    """True iff the corpus dir contains at least one file."""
    root = CONFIG.corpus_dir
    if not root.exists() or not root.is_dir():
        return False
    try:
        return any(p.is_file() for p in root.rglob("*"))
    except OSError:
        return False


def _auth_bootstrapped() -> bool:
    """The auth token file exists on disk (created on first server start)."""
    try:
        return CONFIG.session_token_file.is_file()
    except OSError:
        return False


async def status() -> dict[str, Any]:
    """Everything the frontend needs to decide whether to render the wizard."""
    installed = await _installed_models()
    missing = _recommended_missing(installed)
    workspaces = _workspaces_created()
    corpus = _corpus_downloaded()
    auth = _auth_bootstrapped()
    return {
        "ollama_up": bool(installed) or await _ollama_reachable(),
        "models_installed": installed,
        "recommended_missing": missing,
        "workspaces_created": workspaces,
        "corpus_downloaded": corpus,
        "auth_bootstrapped": auth,
        # Convenience — the frontend uses this as a single signal.
        "needs_setup": bool(missing) or workspaces == 0 or not corpus,
    }


async def _ollama_reachable() -> bool:
    """Reachability probe distinct from _installed_models — an ollama that's
    up but has no models still returns []."""
    client = get_ollama_client()
    try:
        resp = await client.get("/api/tags", timeout=1.5)
        resp.raise_for_status()
        return True
    except (httpx.HTTPError, OSError):
        return False
