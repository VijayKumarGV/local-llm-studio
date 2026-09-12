#!/usr/bin/env python3
"""
Refresh the curated corpus: git-pull each source repo, then re-ingest any
files whose content changed. Idempotent — files whose chunks are already
embedded under the current model are skipped.

Run manually:
    .venv/bin/python scripts/refresh_corpus.py

Or add to cron for weekly refresh:
    0 4 * * 0 cd "/Users/avishwakarma/Desktop/llm model" && .venv/bin/python scripts/refresh_corpus.py >> refresh.log 2>&1
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import database, rag  # noqa: E402

CORPUS = ROOT / "corpus"


def _git_pull(repo_dir: Path) -> tuple[bool, str]:
    if not (repo_dir / ".git").exists():
        return False, "not a git repo"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only", "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        return out.returncode == 0, (out.stderr or out.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "git pull timed out"
    except Exception as e:
        return False, str(e)


def _corpus_repos() -> list[Path]:
    repos = []
    for base in (CORPUS / "security", CORPUS / "coding"):
        if not base.exists():
            continue
        for p in base.iterdir():
            if p.is_dir() and (p / ".git").exists():
                repos.append(p)
    return repos


async def _reingest_project(project_id: str, corpus_dir: Path) -> dict:
    """Re-ingest files under corpus_dir that already belong to project_id.
    Force re-embed to pick up any file content changes."""
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, filepath FROM files WHERE project_id = ?", (project_id,))
        rows = cur.fetchall()
    stats = {"processed": 0, "re_embedded": 0, "skipped": 0, "errors": 0}
    for row in rows:
        fp = Path(row["filepath"])
        if not fp.exists():
            continue
        if str(fp).startswith(str(corpus_dir)):
            stats["processed"] += 1
            try:
                res = await rag.ingest_file(row["id"], force=True)
                if res.get("status") == "success":
                    stats["re_embedded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                print(f"    [err] {fp.name}: {e}")
    return stats


async def main() -> int:
    repos = _corpus_repos()
    if not repos:
        print("No corpus repos found under corpus/ — run scripts/curate_corpus.py first.")
        return 1

    print(f"Refreshing {len(repos)} repo(s)...\n")
    updated_dirs: list[Path] = []
    for repo in repos:
        ok, msg = _git_pull(repo)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {repo.relative_to(ROOT)}  {msg[:80] if msg else ''}")
        if ok:
            updated_dirs.append(repo)

    if not updated_dirs:
        print("\nNo repos updated. Done.")
        return 0

    # Map corpus dirs → project ids by looking up the projects created by build_expert_workspaces
    projects = database.list_projects()
    sec = next((p for p in projects if "Security" in p["name"]), None)
    code = next((p for p in projects if "Coding" in p["name"]), None)

    print(f"\nRe-ingesting changed files ...")
    for d in updated_dirs:
        parent = d.parent.name  # 'security' or 'coding'
        proj = sec if parent == "security" else code
        if not proj:
            continue
        stats = await _reingest_project(proj["id"], d)
        print(f"  {d.name}: {stats}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
