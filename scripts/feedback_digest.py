#!/usr/bin/env python3
"""
Feedback digest — produce a weekly markdown report of thumbs-down
responses so the operator can spot patterns without spelunking SQLite.

Usage
-----
    .venv/bin/python scripts/feedback_digest.py                 # last 7 days
    .venv/bin/python scripts/feedback_digest.py --days 30
    .venv/bin/python scripts/feedback_digest.py --out - --days 1  # stdout

Output
------
- markdown file at `evals/digests/<UTC-week>.md` (default) with:
    - counts by workspace + model
    - the negative-rated user prompts (most recent 20)
    - top word themes across those prompts (simple frequency)

Explicit design choices
-----------------------
* Never LLM-summarize the digest — we want raw signal.
* Small `_STOPWORDS` list, English-only, lower-cased. Enough to filter
  out `the / and / a` when eyeballing themes.
* Reads the live studio DB by default. Override with `--db /path`.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGESTS_DIR = ROOT / "evals" / "digests"

_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both but by could did do does doing down during
    each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just me might more most my
    myself no nor not now of off on once only or other our ours ourselves out
    over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would
    you your yours yourself yourselves
    """.split()
)


def _week_key(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _fetch_downvotes(db_path: Path, since_iso: str) -> list[dict[str, object]]:
    """Assistant messages with rating=-1 in the window, plus a bit of context
    (project, model, user prompt that provoked them)."""
    if not db_path.is_file():
        raise FileNotFoundError(f"DB not found at {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                mf.created_at   AS feedback_at,
                mf.note         AS note,
                m.content       AS assistant_text,
                c.id            AS conversation_id,
                c.model         AS model,
                p.name          AS project_name,
                (SELECT prev.content
                   FROM messages prev
                  WHERE prev.conversation_id = m.conversation_id
                    AND prev.role = 'user'
                    AND prev.created_at < m.created_at
                  ORDER BY prev.created_at DESC LIMIT 1) AS user_prompt
            FROM message_feedback mf
            JOIN messages m       ON m.id = mf.message_id
            JOIN conversations c  ON c.id = m.conversation_id
            LEFT JOIN projects p  ON p.id = c.project_id
            WHERE mf.rating = -1 AND mf.created_at >= ?
            ORDER BY mf.created_at DESC
            """,
            (since_iso,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _group_counts(rows: list[dict[str, object]], key: str) -> Counter[str]:
    return Counter((str(r.get(key)) or "(none)") for r in rows)


def _theme_words(rows: list[dict[str, object]], top_n: int = 20) -> list[tuple[str, int]]:
    """Frequency of non-stopword tokens (>=3 chars) across user prompts."""
    freq: Counter[str] = Counter()
    for r in rows:
        text = (r.get("user_prompt") or "").lower()
        for tok in re.findall(r"[a-z][a-z0-9_-]{2,}", text):
            if tok in _STOPWORDS:
                continue
            freq[tok] += 1
    return freq.most_common(top_n)


def render_markdown(
    rows: list[dict[str, object]],
    since: datetime,
    week_key: str,
    sample_prompts: int = 20,
) -> str:
    lines: list[str] = []
    lines.append(f"# Feedback digest — {week_key}")
    lines.append("")
    lines.append(f"Window: {since.isoformat(timespec='seconds')} → now (UTC)")
    lines.append(f"Total 👎: **{len(rows)}**")
    lines.append("")
    if not rows:
        lines.append("_No negative feedback in this window._")
        return "\n".join(lines) + "\n"

    def _section(title: str, counts: Counter[str]) -> None:
        lines.append(f"## By {title}")
        lines.append("")
        lines.append(f"| {title} | count |")
        lines.append("| --- | ---: |")
        for name, n in counts.most_common():
            lines.append(f"| {name} | {n} |")
        lines.append("")

    _section("workspace", _group_counts(rows, "project_name"))
    _section("model", _group_counts(rows, "model"))

    themes = _theme_words(rows)
    if themes:
        lines.append("## Top prompt themes")
        lines.append("")
        lines.append("_Case-insensitive token frequency across the user prompts that provoked a 👎. Stopwords filtered._")
        lines.append("")
        lines.append("| token | count |")
        lines.append("| --- | ---: |")
        for tok, n in themes:
            lines.append(f"| `{tok}` | {n} |")
        lines.append("")

    lines.append(f"## Recent downvoted prompts (up to {sample_prompts})")
    lines.append("")
    for r in rows[:sample_prompts]:
        prompt = (r.get("user_prompt") or "").replace("\n", " ").strip()
        if len(prompt) > 240:
            prompt = prompt[:237] + "…"
        note = (r.get("note") or "").strip()
        header = f"- **{r.get('feedback_at')}** — workspace `{r.get('project_name') or '(none)'}` · model `{r.get('model')}`"
        if note:
            header += f" · note: _{note}_"
        lines.append(header)
        lines.append(f"    > {prompt}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Feedback digest generator.")
    ap.add_argument("--db", type=Path, default=Path("backend/workspace.db"), help="Path to workspace SQLite DB")
    ap.add_argument("--days", type=int, default=7, help="Look-back window in days (default 7)")
    ap.add_argument("--out", default=None, help="Output file path, or '-' for stdout. Default: evals/digests/<week>.md")
    args = ap.parse_args(argv)

    now = datetime.now(UTC)
    since = now - timedelta(days=args.days)
    week_key = _week_key(now)

    rows = _fetch_downvotes(args.db, since.isoformat(timespec="seconds"))
    md = render_markdown(rows, since, week_key)

    if args.out == "-":
        sys.stdout.write(md)
        return 0
    out_path = Path(args.out) if args.out else (DIGESTS_DIR / f"{week_key}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"wrote {out_path}  ({len(rows)} downvotes over {args.days}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
