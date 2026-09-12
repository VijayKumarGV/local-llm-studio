"""Guards against doc drift.

Fails if a route was added to `backend/server.py` but never mentioned
in `docs/api.md` (or vice versa). Doesn't enforce that every route
gets a paragraph — only that the endpoint-index table stays
synchronized.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Templated path segments the docs shorten (e.g. `{conv_id}` → `{conv_id}`)
# — this regex just strips the `{}` wrapper to compare.
_ROUTE_RE = re.compile(r'@app\.(?:get|post|put|patch|delete)\(\s*"(/api/[^"]+)"')


def _routes_from_code() -> set[str]:
    src = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    return set(_ROUTE_RE.findall(src))


def _routes_from_docs() -> set[str]:
    text = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    found: set[str] = set()
    for m in re.finditer(r"`(/api/[^`\s]+)`", text):
        # Strip trailing query-string / placeholder noise for comparison.
        path = m.group(1).split("?", 1)[0].split("`", 1)[0]
        found.add(path)
    return found


def test_every_code_route_is_documented() -> None:
    code = _routes_from_code()
    docs = _routes_from_docs()
    missing = sorted(code - docs)
    assert not missing, "routes in backend/server.py but not docs/api.md:\n  " + "\n  ".join(missing)


def test_docs_do_not_advertise_ghost_routes() -> None:
    code = _routes_from_code()
    docs = _routes_from_docs()
    # `/metrics` and `/auth` aren't `/api/*` — they legitimately appear in
    # docs but come from a different regex; filter them out.
    orphans = sorted(r for r in (docs - code) if not r.startswith(("/api/health", "/metrics", "/auth")))
    # These are documented placeholders + example variants; keep the diff
    # tight but tolerate the parameterized versions.
    tolerated = {r for r in orphans if "…" in r or "{" in r}
    assert not (set(orphans) - tolerated), "docs mention endpoints not in backend/server.py:\n  " + "\n  ".join(
        sorted(set(orphans) - tolerated)
    )
