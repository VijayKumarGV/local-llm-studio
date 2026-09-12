"""
Simple pull-based update check.

On tray launch (best-effort, non-blocking), hit the GitHub Releases API
for the configured repo. If the latest published tag is a higher semver
than the bundled version, return the (version, url) tuple so the tray
can notify the user. We *never* auto-download or auto-install — just
surface a link.

The tuple parsing gives us stable ordering across
'0.9.0' vs '0.10.0' vs '1.0.0-rc1' — see `_semver_key`.
"""

from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger("studio.updater")

# Bumped in lockstep with git tags. Kept in-source so a frozen .app can
# tell whether it's stale without needing a manifest file.
CURRENT_VERSION = "1.0.0-rc.1"


def _semver_key(v: str) -> tuple[int, ...]:
    """Turn '1.2.3' → (1, 2, 3). Pre-release suffixes ('1.2.3-rc1') are
    stripped for comparison — safe for our monotonic-tag scheme."""
    core = re.split(r"[-+]", v.lstrip("v"), maxsplit=1)[0]
    parts = core.split(".")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def is_newer(candidate: str, baseline: str = CURRENT_VERSION) -> bool:
    """Semver-aware comparison. Returns True iff `candidate` > `baseline`."""
    return _semver_key(candidate) > _semver_key(baseline)


def check_latest(
    repo: str,
    baseline: str = CURRENT_VERSION,
    timeout_s: float = 5.0,
    client: httpx.Client | None = None,
) -> tuple[str, str] | None:
    """Look up `repo`'s latest GitHub release. Returns (version, html_url)
    if newer than `baseline`, else None. Network errors are swallowed —
    an update check is best-effort and must never crash the tray."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        r = client.get(url, timeout=timeout_s) if client is not None else httpx.get(url, timeout=timeout_s)
        r.raise_for_status()
    except Exception as e:  # network / 4xx / 5xx / parse
        log.info("update check failed: %s", e)
        return None
    try:
        data = r.json()
        tag = str(data.get("tag_name", "")).lstrip("v")
        page = str(data.get("html_url", ""))
    except (ValueError, AttributeError):
        return None
    if not tag or not page:
        return None
    if is_newer(tag, baseline):
        return tag, page
    return None
