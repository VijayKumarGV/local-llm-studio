"""
Prompt template loader.

System / instruction prompts live as Markdown files under `prompts/` so
they're git-tracked, PR-reviewable, and can be exercised by the eval
harness. Loads are cached — call `reload()` after monkey-patching a
file in tests.

Keeping the loader tiny on purpose: no Jinja, no {placeholders}. Every
prompt file is loaded verbatim (stripped of surrounding whitespace).
Composition happens at the call site.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """Explicit type so callers can distinguish 'prompt file missing' from
    generic filesystem errors."""


@lru_cache(maxsize=64)
def load(name: str) -> str:
    """Return the contents of `prompts/{name}.md`, stripped. Result is
    cached — call `reload()` to invalidate."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"no prompt at {path}")
    return path.read_text(encoding="utf-8").strip()


def reload() -> None:
    """Drop the load-cache. Call this in tests after modifying prompts on
    disk to force a re-read."""
    load.cache_clear()
