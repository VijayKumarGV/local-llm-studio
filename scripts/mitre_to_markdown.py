#!/usr/bin/env python3
"""
Explode the MITRE ATT&CK Enterprise STIX bundle into one markdown file per
attack technique, tactic, and mitigation. The raw JSON is 50+ MB of STIX
metadata that's terrible for RAG chunking; per-technique markdowns are
compact, semantically coherent, and match how humans actually query
("what is T1055", "SQL injection detection").

After running, deletes the raw JSON so it isn't ingested.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MITRE_ROOT = ROOT / "corpus" / "security" / "mitre_attack"
RAW_JSON = MITRE_ROOT / "enterprise-attack" / "enterprise-attack.json"
OUT_DIR = MITRE_ROOT / "techniques"


def external_id(obj: dict) -> str:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id", "")
    return ""


def safe_slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s.strip())
    return s[:80] or "unnamed"


def to_markdown(obj: dict) -> tuple[str, str]:
    """Return (kind_folder, filename, body)."""
    kind = obj.get("type", "unknown")
    name = obj.get("name", "unnamed")
    ext_id = external_id(obj)
    desc = obj.get("description", "").strip()
    kill_chain = obj.get("kill_chain_phases", []) or []
    platforms = obj.get("x_mitre_platforms", []) or []
    detection = obj.get("x_mitre_detection", "").strip()
    data_sources = obj.get("x_mitre_data_sources", []) or []
    permissions = obj.get("x_mitre_permissions_required", []) or []
    version = obj.get("x_mitre_version", "")
    is_subtechnique = obj.get("x_mitre_is_subtechnique", False)

    parts = [f"# {ext_id or 'ATT&CK'} — {name}\n"]
    parts.append(f"**Type:** `{kind}`" + (f" (sub-technique)" if is_subtechnique else "") + "\n")
    if kill_chain:
        chains = ", ".join(f"{p.get('kill_chain_name')}/{p.get('phase_name')}" for p in kill_chain)
        parts.append(f"**Kill-chain phases:** {chains}\n")
    if platforms:
        parts.append(f"**Platforms:** {', '.join(platforms)}\n")
    if data_sources:
        parts.append(f"**Data sources:** {', '.join(data_sources)}\n")
    if permissions:
        parts.append(f"**Permissions required:** {', '.join(permissions)}\n")
    if version:
        parts.append(f"**Version:** {version}\n")
    if desc:
        parts.append("\n## Description\n\n" + desc + "\n")
    if detection:
        parts.append("\n## Detection\n\n" + detection + "\n")
    body = "".join(parts)
    filename = f"{ext_id + '_' if ext_id else ''}{safe_slug(name)}.md"
    kind_folder = {
        "attack-pattern": "techniques",
        "x-mitre-tactic": "tactics",
        "course-of-action": "mitigations",
        "intrusion-set": "groups",
        "malware": "software_malware",
        "tool": "software_tools",
    }.get(kind, "other")
    return kind_folder, filename, body


def main() -> int:
    if not RAW_JSON.exists():
        print(f"[skip] no MITRE JSON at {RAW_JSON}")
        return 0

    print(f"[load] {RAW_JSON} ({RAW_JSON.stat().st_size / 1e6:.1f} MB) ...")
    bundle = json.loads(RAW_JSON.read_text())
    objects = bundle.get("objects") or []
    print(f"[load] {len(objects)} STIX objects")

    interesting_kinds = {"attack-pattern", "x-mitre-tactic", "course-of-action", "intrusion-set", "malware", "tool"}
    written = 0
    OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    for obj in objects:
        if obj.get("type") not in interesting_kinds:
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        folder, filename, body = to_markdown(obj)
        target_dir = MITRE_ROOT / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / filename).write_text(body, encoding="utf-8")
        written += 1

    print(f"[write] {written} markdown files under {MITRE_ROOT.relative_to(ROOT)}/")

    # Remove the raw JSON so it isn't ingested (way too big for RAG).
    print(f"[cleanup] removing raw JSON")
    RAW_JSON.unlink()
    ent_dir = RAW_JSON.parent
    if ent_dir.exists() and not any(ent_dir.iterdir()):
        ent_dir.rmdir()

    return 0


if __name__ == "__main__":
    sys.exit(main())
