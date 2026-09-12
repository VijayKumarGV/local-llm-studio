"""Centralized configuration.

Every knob the operator can turn lives here. Rules:

  1. Every value is env-overridable.
  2. Defaults are sane for a fresh macOS install (data under Library/
     Application Support, Ollama at 127.0.0.1:11434, etc.).
  3. The `CONFIG` singleton is built once at import time. Test code
     that wants a different config either monkey-patches attributes or
     rebuilds via `_load()`.

DO NOT read os.environ directly from other modules — always go through
`from backend.config import CONFIG`. This gives ops one place to
document every knob (see docs / README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser() if v else default


def _default_data_dir() -> Path:
    """Where SQLite, uploads, backups, and generated artifacts live."""
    return Path.home() / "Library/Application Support/LocalLLMStudio"


@dataclass(frozen=True)
class Config:
    # ── Paths (env-overridable) ─────────────────────────────────────
    data_dir: Path
    db_path: Path
    upload_dir: Path
    artifacts_dir: Path
    scratch_dir: Path
    corpus_dir: Path
    session_token_file: Path

    # ── Network ─────────────────────────────────────────────────────
    bind_host: str
    bind_port: int
    ollama_host: str

    # ── Auth ────────────────────────────────────────────────────────
    session_token_env: str | None  # value pulled from SESSION_TOKEN if set

    # ── Logging ─────────────────────────────────────────────────────
    log_level: str

    # ── Sandbox ─────────────────────────────────────────────────────
    sandbox_image: str
    allow_unsandboxed: bool

    # ── Rate limits ─────────────────────────────────────────────────
    rate_limit_default: str
    rate_limit_chat: str
    rate_limit_sandbox: str
    rate_limit_upload: str
    rate_limit_compare: str

    # ── Feature flags ───────────────────────────────────────────────
    disable_keyring: bool

    # ── Metadata ────────────────────────────────────────────────────
    env_names: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "STUDIO_DATA_DIR",
                "STUDIO_DB_PATH",
                "STUDIO_UPLOAD_DIR",
                "STUDIO_ARTIFACTS_DIR",
                "STUDIO_SCRATCH_DIR",
                "STUDIO_CORPUS_DIR",
                "STUDIO_TOKEN_FILE",
                "BIND_HOST",
                "BIND_PORT",
                "OLLAMA_HOST",
                "SESSION_TOKEN",
                "LOG_LEVEL",
                "STUDIO_SANDBOX_IMAGE",
                "STUDIO_ALLOW_UNSANDBOXED",
                "STUDIO_RATE_LIMIT_DEFAULT",
                "STUDIO_RATE_LIMIT_CHAT",
                "STUDIO_RATE_LIMIT_SANDBOX",
                "STUDIO_RATE_LIMIT_UPLOAD",
                "STUDIO_RATE_LIMIT_COMPARE",
                "STUDIO_DISABLE_KEYRING",
            }
        )
    )


def _load() -> Config:
    data = _env_path("STUDIO_DATA_DIR", _default_data_dir())
    data.mkdir(parents=True, exist_ok=True)

    project_root = Path(__file__).resolve().parent.parent
    default_upload = Path(__file__).resolve().parent / "uploads"
    default_artifacts = Path(__file__).resolve().parent / "artifacts"
    default_scratch = default_upload / "scratch"

    return Config(
        data_dir=data,
        db_path=_env_path("STUDIO_DB_PATH", Path(__file__).resolve().parent / "workspace.db"),
        upload_dir=_env_path("STUDIO_UPLOAD_DIR", default_upload),
        artifacts_dir=_env_path("STUDIO_ARTIFACTS_DIR", default_artifacts),
        scratch_dir=_env_path("STUDIO_SCRATCH_DIR", default_scratch),
        corpus_dir=_env_path("STUDIO_CORPUS_DIR", project_root / "corpus"),
        session_token_file=_env_path(
            "STUDIO_TOKEN_FILE",
            data / "token",
        ),
        bind_host=os.environ.get("BIND_HOST", "127.0.0.1"),
        bind_port=int(os.environ.get("BIND_PORT", "8080")),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        session_token_env=os.environ.get("SESSION_TOKEN"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        sandbox_image=os.environ.get("STUDIO_SANDBOX_IMAGE", "studio-sandbox:latest"),
        allow_unsandboxed=_env_bool("STUDIO_ALLOW_UNSANDBOXED", False),
        rate_limit_default=os.environ.get("STUDIO_RATE_LIMIT_DEFAULT", "120/minute"),
        rate_limit_chat=os.environ.get("STUDIO_RATE_LIMIT_CHAT", "20/minute"),
        rate_limit_sandbox=os.environ.get("STUDIO_RATE_LIMIT_SANDBOX", "30/minute"),
        rate_limit_upload=os.environ.get("STUDIO_RATE_LIMIT_UPLOAD", "60/hour"),
        rate_limit_compare=os.environ.get("STUDIO_RATE_LIMIT_COMPARE", "10/minute"),
        disable_keyring=_env_bool("STUDIO_DISABLE_KEYRING", False),
    )


CONFIG: Config = _load()


def reload() -> Config:
    """Test-only: rebuild CONFIG after monkeypatching os.environ."""
    global CONFIG
    CONFIG = _load()
    return CONFIG
