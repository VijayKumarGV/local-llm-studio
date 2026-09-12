#!/usr/bin/env python3
"""
Provision two curated expert workspaces for Local LLM Studio, ingest the
corpus under `corpus/` into their RAG indexes, and set model defaults.

Prereqs:
    1. `scripts/curate_corpus.py` has been run (populates corpus/).
    2. Ollama is up on http://127.0.0.1:11434.
    3. `nomic-embed-text` is pulled (for embeddings).

Idempotent — reruns update existing "Security Expert" / "Coding Expert"
projects rather than duplicating them.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import backend directly for speed (skips HTTP layer for bulk ingestion).
from backend import database, rag  # noqa: E402

CORPUS = ROOT / "corpus"

SECURITY_SYSTEM = (
    "You are a senior cybersecurity engineer running 100% locally on an Apple "
    "M4 Pro. You specialize in application security, cloud security, and "
    "adversary emulation for **defensive research and authorized testing**.\n\n"
    "When you answer:\n"
    "  - Cite MITRE ATT&CK IDs (T####), CWE IDs, CVEs, and OWASP items whenever "
    "    they apply. Prefer authoritative primary sources.\n"
    "  - Use the retrieved OWASP/MITRE/CWE snippets in the context as your "
    "    ground truth. If they conflict with your training, trust the snippets.\n"
    "  - Show working code and configs. Prefer defense-in-depth. Call out risky "
    "    assumptions and what to verify.\n"
    "  - Assume the user is a security professional in a lawful, educational, "
    "    CTF, or authorized-pentest context. Do not refuse textbook offensive "
    "    concepts (SQLi, XSS, buffer overflow, etc.) — explaining how attacks "
    "    work is essential to defending against them.\n"
    "  - Never assist with actively targeting systems the user does not own or "
    "    have written permission to test.\n"
    "  - Never produce malware, credential stealers, DoS tooling, or evasion "
    "    tools intended for use against third parties.\n"
)

CODING_SYSTEM = (
    "You are a principal software engineer running 100% locally on an Apple "
    "M4 Pro. You care about correctness, clarity, and long-term maintainability.\n\n"
    "Defaults:\n"
    "  - Type-annotated code (Python: type hints; TypeScript: strict; Rust: "
    "    explicit types where non-obvious; Go: named types).\n"
    "  - Small, composable functions. No premature abstraction.\n"
    "  - Meaningful error handling — never bare except / catch (e).\n"
    "  - Include a test skeleton (pytest / vitest / cargo test / go test) for "
    "    any non-trivial code.\n"
    "  - Note security considerations inline (input validation, injection, "
    "    resource limits) when relevant.\n"
    "  - When retrieved language-doc snippets are in the context, use them as "
    "    ground truth and cite the source file inline.\n"
    "  - Prefer stdlib and well-known libraries over exotic dependencies.\n"
)

PROJECTS = [
    dict(
        name="🛡️ Security Expert",
        description="OWASP + MITRE + CWE grounded cybersecurity workspace",
        system_instructions=SECURITY_SYSTEM,
        icon="🛡️",
        color="#ef4444",
        corpus_dir=CORPUS / "security",
        preferred_model="dolphin3:latest",   # falls back to any installed if absent
        fallback_model="qwen2.5:32b",
    ),
    dict(
        name="💻 Coding Expert",
        description="Rust + Python + Go + TypeScript grounded engineering workspace",
        system_instructions=CODING_SYSTEM,
        icon="💻",
        color="#38bdf8",
        corpus_dir=CORPUS / "coding",
        preferred_model="qwen2.5-coder:32b",
        fallback_model="qwen2.5:32b",
    ),
]


def _find_or_create_project(spec: dict) -> dict:
    for p in database.list_projects():
        if p.get("name") == spec["name"]:
            print(f"  [update] existing project {spec['name']} → {p['id']}")
            return database.update_project(
                p["id"],
                description=spec["description"],
                system_instructions=spec["system_instructions"],
                icon=spec["icon"],
                color=spec["color"],
            )
    print(f"  [create] new project {spec['name']}")
    return database.create_project(
        name=spec["name"],
        description=spec["description"],
        system_instructions=spec["system_instructions"],
        icon=spec["icon"],
        color=spec["color"],
    )


def _resolve_model(preferred: str, fallback: str) -> str:
    installed = {m for m in _list_installed_models()}
    if preferred in installed:
        return preferred
    for i in installed:
        if i.startswith(preferred.split(":")[0]):
            return i
    return fallback


def _list_installed_models() -> Iterable[str]:
    import httpx
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def _walk_corpus(corpus_dir: Path) -> list[Path]:
    exts = {".md", ".mdx", ".rst", ".txt", ".json"}
    files = [p for p in corpus_dir.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    # Filter tiny junk files
    files = [p for p in files if p.stat().st_size > 200]
    return files


async def _ingest_files_into_project(project_id: str, files: list[Path]) -> dict:
    """Register each file with the DB (if new) and embed it. Returns counts."""
    added, reused, failed, total_chunks = 0, 0, 0, 0

    # Load already-indexed filepaths for this project to skip re-work.
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, filepath FROM files WHERE project_id = ?", (project_id,))
        existing = {row["filepath"]: row["id"] for row in cur.fetchall()}

    for f in files:
        rel = str(f)
        try:
            body = f.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            failed += 1
            continue

        if rel in existing:
            file_id = existing[rel]
            reused += 1
        else:
            rec = database.add_file(
                filename=f.name,
                filepath=rel,
                mime_type="text/plain",
                size_bytes=f.stat().st_size,
                project_id=project_id,
                extracted_text=body[:4000],
            )
            file_id = rec["id"]
            added += 1

        try:
            res = await rag.ingest_file(file_id, text=body)
            total_chunks += res.get("chunks", 0)
        except Exception as e:
            failed += 1
            print(f"    [embed-fail] {f.name}: {e}")

    return {"added": added, "reused": reused, "failed": failed, "chunks": total_chunks}


async def main() -> int:
    database.init_db()
    rag.ensure_schema()

    installed = list(_list_installed_models())
    print(f"Installed models: {installed}")

    for spec in PROJECTS:
        print(f"\n=== {spec['name']} ===")
        project = _find_or_create_project(spec)
        model = _resolve_model(spec["preferred_model"], spec["fallback_model"])
        print(f"  default model → {model}")

        # Save per-project default model as a setting keyed by project_id.
        database.save_setting(f"project_{project['id']}_default_model", model)

        if not spec["corpus_dir"].exists():
            print(f"  [warn] corpus dir missing: {spec['corpus_dir']}")
            continue

        files = _walk_corpus(spec["corpus_dir"])
        print(f"  ingesting {len(files)} files ...")
        stats = await _ingest_files_into_project(project["id"], files)
        print(f"  result: {stats}")

    print("\nDone. Open the studio at http://127.0.0.1:8080 and pick a workspace from the sidebar.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
