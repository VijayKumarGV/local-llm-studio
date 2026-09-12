#!/usr/bin/env python3
"""
Corpus curator for Local LLM Studio expert mode.

Downloads a curated set of *authentic, primary-source, appropriately-licensed*
reference documents into `corpus/` so RAG can retrieve them.

All sources are public, official (from the project's canonical repo/host),
and released under permissive licenses (MIT, Apache 2.0, CC-BY, PSF, or
public domain / U.S. gov work). Nothing scraped from paywalled or
copyrighted material.

Run:  python scripts/curate_corpus.py
Idempotent — re-runs skip already-cloned repos.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
SECURITY = CORPUS / "security"
CODING = CORPUS / "coding"


# name -> (git_url, keep_globs, target_subdir, license, description)
SOURCES = [
    # ---------- SECURITY ----------
    dict(
        name="OWASP Cheat Sheet Series",
        url="https://github.com/OWASP/CheatSheetSeries.git",
        target=SECURITY / "owasp_cheatsheets",
        keep=["cheatsheets"],
        license="CC-BY-SA 4.0",
    ),
    dict(
        name="OWASP Top 10 (2021)",
        url="https://github.com/OWASP/Top10.git",
        target=SECURITY / "owasp_top10",
        keep=["2021/docs"],
        license="CC-BY-SA 4.0",
    ),
    dict(
        name="OWASP ASVS",
        url="https://github.com/OWASP/ASVS.git",
        target=SECURITY / "owasp_asvs",
        keep=["5.0/en"],
        license="CC-BY-SA 4.0",
    ),
    dict(
        name="MITRE CTI (ATT&CK)",
        url="https://github.com/mitre-attack/attack-stix-data.git",
        target=SECURITY / "mitre_attack",
        keep=["enterprise-attack/enterprise-attack.json"],
        license="U.S. Government Work (public)",
    ),
    dict(
        name="PayloadsAllTheThings",
        url="https://github.com/swisskyrepo/PayloadsAllTheThings.git",
        target=SECURITY / "payloads",
        keep=["README.md"],  # keep only READMEs — index summaries per attack class
        keep_pattern="README.md",
        license="MIT",
    ),
    # ---------- CODING ----------
    dict(
        name="The Rust Programming Language Book",
        url="https://github.com/rust-lang/book.git",
        target=CODING / "rust_book",
        keep=["src"],
        license="Apache-2.0 / MIT",
    ),
    dict(
        name="Python cpython docs (tutorial + howto)",
        url="https://github.com/python/cpython.git",
        target=CODING / "python_docs",
        keep=["Doc/tutorial", "Doc/howto"],
        license="PSF",
    ),
    dict(
        name="Go Blog + Effective Go",
        url="https://github.com/golang/website.git",
        target=CODING / "go_docs",
        keep=["_content/doc"],
        license="CC-BY-3.0",
    ),
    dict(
        name="TypeScript Handbook",
        url="https://github.com/microsoft/TypeScript-Website.git",
        target=CODING / "typescript_handbook",
        keep=["packages/documentation/copy/en/handbook-v2"],
        license="MIT",
    ),
]


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(cmd))
    subprocess.check_call(cmd, cwd=cwd)


def shallow_clone(name: str, url: str, target: Path, keep: list[str]) -> None:
    if target.exists() and any(target.iterdir()):
        print(f"[skip] {name} — already at {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    print(f"[clone] {name} → {target.relative_to(ROOT)}")
    _run(
        [
            "git", "clone",
            "--depth", "1",
            "--filter=blob:none",
            "--sparse",
            url,
            str(target),
        ]
    )
    _run(["git", "-C", str(target), "sparse-checkout", "set", "--no-cone", *keep])


def prune_non_content(target: Path, extensions: set[str]) -> int:
    """Remove files whose extension isn't in `extensions`. Returns count removed."""
    removed = 0
    for p in target.rglob("*"):
        if p.is_file() and p.suffix.lower() not in extensions and p.name != "README.md":
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    # collapse empty dirs
    for d in sorted(target.rglob("*"), key=lambda x: -len(str(x))):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


def main() -> int:
    SECURITY.mkdir(parents=True, exist_ok=True)
    CODING.mkdir(parents=True, exist_ok=True)

    ok, failed = [], []
    for src in SOURCES:
        try:
            shallow_clone(src["name"], src["url"], src["target"], src["keep"])
            ok.append(src["name"])
        except subprocess.CalledProcessError as e:
            failed.append((src["name"], str(e)))
            print(f"[fail] {src['name']}: {e}")

    # Prune non-doc files (keep .md, .rst, .txt, .json, .mdx) to shrink corpus and
    # avoid ingesting build scripts, images, etc.
    keep_exts = {".md", ".mdx", ".rst", ".txt", ".json"}
    for src in SOURCES:
        if src["target"].exists():
            removed = prune_non_content(src["target"], keep_exts)
            if removed:
                print(f"[prune] {src['name']}: removed {removed} non-doc files")

    print()
    print(f"Curated {len(ok)} / {len(SOURCES)} sources.")
    if failed:
        print("Failures:")
        for name, err in failed:
            print(f"  - {name}: {err}")

    # Summary of corpus size
    total_files = sum(1 for _ in CORPUS.rglob("*") if _.is_file())
    print(f"Corpus contains {total_files} files under {CORPUS.relative_to(ROOT)}/")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
