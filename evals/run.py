"""
Eval runner for Local LLM Studio.

Loads a JSONL spec (see evals/README.md for the format), issues real
requests against a running studio server, computes per-spec pass/fail,
writes a JSON report to `evals/history/`, and optionally exits nonzero
if the aggregate pass_rate regressed relative to the last report on
disk.

Usage
-----
    .venv/bin/python evals/run.py \\
        --spec evals/security_expert.jsonl \\
        --server http://127.0.0.1:8080 \\
        --token "$SESSION_TOKEN" \\
        --model qwen2.5:32b

    # regression-gate mode
    .venv/bin/python evals/run.py --spec evals/coding_expert.jsonl --compare-baseline

Design notes
------------
Every check is a *deterministic* string match — no LLM-as-judge. The
runner concatenates all `event: token` deltas from `/api/chat/stream`,
using the final `event: done` payload as ground truth when present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("evals.run")

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "evals" / "history"
DEFAULT_SERVER = "http://127.0.0.1:8080"
DEFAULT_MODEL = "qwen2.5:32b"
DEFAULT_TOP_K = 6
REGRESSION_THRESHOLD = 0.02  # 2 percentage points

WORKSPACE_TO_PROJECT_NAME = {
    "security": "Security Expert",
    "coding": "Coding Expert",
}


# ── Spec I/O ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Spec:
    id: str
    query: str
    workspace: str
    expected_sources: tuple[str, ...] = ()
    answer_must_contain: tuple[str, ...] = ()
    answer_must_not_contain: tuple[str, ...] = ()
    expected_technique_ids: tuple[str, ...] = ()


def load_spec(path: Path) -> list[Spec]:
    """Parse a JSONL spec. Skips blank lines. Validates required fields."""
    out: list[Spec] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path.name}:{lineno} not valid JSON: {e}") from e
        for req in ("id", "query", "workspace"):
            if req not in obj:
                raise ValueError(f"{path.name}:{lineno} missing required '{req}'")
        # At least one grading signal must exist.
        if not any(
            obj.get(k)
            for k in ("expected_sources", "answer_must_contain", "answer_must_not_contain", "expected_technique_ids")
        ):
            raise ValueError(f"{path.name}:{lineno} spec {obj['id']} has no grading signals")
        out.append(
            Spec(
                id=obj["id"],
                query=obj["query"],
                workspace=obj["workspace"],
                expected_sources=tuple(obj.get("expected_sources") or ()),
                answer_must_contain=tuple(obj.get("answer_must_contain") or ()),
                answer_must_not_contain=tuple(obj.get("answer_must_not_contain") or ()),
                expected_technique_ids=tuple(obj.get("expected_technique_ids") or ()),
            )
        )
    return out


# ── Grading primitives ────────────────────────────────────────────────


def check_retrieval(hit_filenames: list[str], expected_sources: tuple[str, ...]) -> bool:
    """True if ANY expected substring matches ANY retrieved filename
    (case-insensitive). Vacuously True if no expectations."""
    if not expected_sources:
        return True
    haystack = [fn.lower() for fn in hit_filenames]
    return any(any(exp.lower() in fn for fn in haystack) for exp in expected_sources)


def check_must_contain(answer: str, must_contain: tuple[str, ...]) -> bool:
    """True if EVERY substring appears (case-insensitive). Vacuous ⇒ True."""
    if not must_contain:
        return True
    lo = answer.lower()
    return all(s.lower() in lo for s in must_contain)


def check_must_not_contain(answer: str, must_not_contain: tuple[str, ...]) -> bool:
    """True if EVERY substring is absent (case-insensitive). Vacuous ⇒ True."""
    if not must_not_contain:
        return True
    lo = answer.lower()
    return all(s.lower() not in lo for s in must_not_contain)


def check_technique_ids(answer: str, expected_ids: tuple[str, ...]) -> bool:
    """True if EVERY MITRE technique ID appears (case-sensitive is fine —
    ATT&CK IDs are canonical uppercase). Vacuous ⇒ True."""
    if not expected_ids:
        return True
    return all(tid in answer for tid in expected_ids)


# ── SSE parsing ───────────────────────────────────────────────────────

_EVENT_RE = re.compile(r"^event:\s*(?P<name>\S+)\s*$")
_DATA_RE = re.compile(r"^data:\s*(?P<payload>.*)$")


def parse_sse_answer(sse_text: str) -> str:
    """Extract the final assistant answer from an SSE stream body.

    Prefers the `event: done` payload's `content` field when present
    (that's the authoritative aggregation the orchestrator emits).
    Falls back to concatenating `event: token` deltas.
    """
    events: list[tuple[str, str]] = []
    current_event: str | None = None
    current_data: list[str] = []
    for line in sse_text.splitlines():
        if not line.strip():
            if current_event and current_data:
                events.append((current_event, "\n".join(current_data)))
            current_event = None
            current_data = []
            continue
        if m := _EVENT_RE.match(line):
            current_event = m.group("name")
        elif m := _DATA_RE.match(line):
            current_data.append(m.group("payload"))
    if current_event and current_data:
        events.append((current_event, "\n".join(current_data)))

    for name, data in reversed(events):
        if name == "done":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                return content

    tokens: list[str] = []
    for name, data in events:
        if name != "token":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        delta = payload.get("delta")
        if isinstance(delta, str):
            tokens.append(delta)
    return "".join(tokens)


# ── Live-server client ────────────────────────────────────────────────


async def resolve_project_id(client: httpx.AsyncClient, workspace: str) -> str | None:
    """Look up the project ID for a workspace by matching on project name."""
    try:
        r = await client.get("/api/projects", timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.warning("resolve_project_id: /api/projects failed: %s", e)
        return None
    want = WORKSPACE_TO_PROJECT_NAME.get(workspace, workspace)
    for p in r.json().get("projects", []):
        if p.get("name", "").lower() == want.lower():
            return str(p.get("id"))
    return None


async def rag_hits(client: httpx.AsyncClient, query: str, project_id: str, top_k: int = DEFAULT_TOP_K) -> list[str]:
    r = await client.get(
        "/api/rag/query",
        params={"q": query, "project_id": project_id, "top_k": top_k},
        timeout=30,
    )
    r.raise_for_status()
    return [h.get("filename", "") for h in r.json().get("hits", [])]


async def chat_answer(
    client: httpx.AsyncClient,
    query: str,
    model: str,
    conversation_id: str,
) -> str:
    r = await client.post(
        "/api/chat/stream",
        json={"conversation_id": conversation_id, "message": query, "model": model},
        timeout=300,
    )
    r.raise_for_status()
    return parse_sse_answer(r.text)


async def create_conversation(client: httpx.AsyncClient, project_id: str, spec_id: str) -> str:
    r = await client.post(
        "/api/conversations",
        json={"project_id": project_id, "title": f"eval:{spec_id}"},
        timeout=10,
    )
    r.raise_for_status()
    return str(r.json()["conversation"]["id"])


async def evaluate_spec(
    client: httpx.AsyncClient,
    spec: Spec,
    project_id: str,
    model: str,
) -> dict[str, Any]:
    """Run one spec end-to-end. Never raises — errors get captured into
    the result dict so a broken request doesn't fail the whole run."""
    result: dict[str, Any] = {"id": spec.id}
    try:
        hits = await rag_hits(client, spec.query, project_id)
    except Exception as e:
        result["retrieval_error"] = str(e)
        hits = []
    result["retrieval_hits"] = hits
    result["retrieval_hit"] = check_retrieval(hits, spec.expected_sources)

    try:
        conv_id = await create_conversation(client, project_id, spec.id)
        answer = await chat_answer(client, spec.query, model, conv_id)
    except Exception as e:
        result["answer_error"] = str(e)
        answer = ""
    result["answer_len"] = len(answer)
    result["must_contain_hit"] = check_must_contain(answer, spec.answer_must_contain)
    result["must_not_contain_avoided"] = check_must_not_contain(answer, spec.answer_must_not_contain)
    result["technique_ids_hit"] = check_technique_ids(answer, spec.expected_technique_ids)
    result["pass"] = all(
        (
            result["retrieval_hit"],
            result["must_contain_hit"],
            result["must_not_contain_avoided"],
            result["technique_ids_hit"],
        )
    )
    return result


# ── Reporting ─────────────────────────────────────────────────────────


def _spec_key(spec_path: Path) -> str:
    """Normalize a spec path for the report + baseline-matching key."""
    if spec_path.is_absolute():
        try:
            return str(spec_path.relative_to(ROOT))
        except ValueError:
            return str(spec_path)
    return str(spec_path)


def build_report(
    spec_path: Path,
    results: list[dict[str, Any]],
    server: str,
    model: str,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec_file": _spec_key(spec_path),
        "server": server,
        "model": model,
        "counts": {"total": total, "pass": passed, "fail": total - passed},
        "pass_rate": (passed / total) if total else 0.0,
        "results": results,
    }


def write_report(report: dict[str, Any], history_dir: Path = HISTORY_DIR) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out = history_dir / f"{ts}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    latest = history_dir / "latest.json"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out.name)  # relative symlink → survives directory moves
    except OSError:
        latest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def load_baseline(spec_path: Path, history_dir: Path = HISTORY_DIR) -> dict[str, Any] | None:
    """Newest prior report for the same spec file, or None if this is the
    first run."""
    if not history_dir.exists():
        return None
    spec_rel = _spec_key(spec_path)
    candidates: list[tuple[str, Path]] = []
    for p in history_dir.iterdir():
        if not p.is_file() or p.suffix != ".json" or p.name == "latest.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("spec_file") == spec_rel:
            candidates.append((data.get("generated_at", ""), p))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return json.loads(candidates[0][1].read_text(encoding="utf-8"))


def diff_against_baseline(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Return regressions (pass→fail per id) and pass-rate delta."""
    was = {r["id"]: bool(r.get("pass")) for r in baseline.get("results", [])}
    regressions: list[dict[str, Any]] = []
    for r in current["results"]:
        rid = r["id"]
        if rid in was and was[rid] and not r.get("pass"):
            regressions.append({"id": rid, "was": True, "now": False})
    return {
        "regressions": regressions,
        "pass_rate_delta": round(current["pass_rate"] - baseline.get("pass_rate", 0.0), 4),
    }


# ── CLI ───────────────────────────────────────────────────────────────


async def _run(
    spec_path: Path,
    server: str,
    token: str | None,
    model: str,
    project_id: str | None,
) -> dict[str, Any]:
    specs = load_spec(spec_path)
    if not specs:
        raise SystemExit(f"[eval] no specs found in {spec_path}")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=server.rstrip("/"), headers=headers) as client:
        workspaces = {s.workspace for s in specs}
        resolved: dict[str, str] = {}
        for ws in workspaces:
            pid = project_id or await resolve_project_id(client, ws)
            if not pid:
                raise SystemExit(f"[eval] could not resolve project for workspace={ws!r}")
            resolved[ws] = pid
        for spec in specs:
            pid = resolved[spec.workspace]
            log.info("running %s (workspace=%s, project_id=%s)", spec.id, spec.workspace, pid)
            results.append(await evaluate_spec(client, spec, pid, model))
    return build_report(spec_path, results, server, model)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run studio evals against a live server.")
    p.add_argument("--spec", type=Path, required=True, help="Path to JSONL spec file")
    p.add_argument("--server", default=os.environ.get("STUDIO_SERVER", DEFAULT_SERVER))
    p.add_argument("--token", default=os.environ.get("SESSION_TOKEN"))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--project-id", default=None, help="Skip workspace auto-detect")
    p.add_argument("--compare-baseline", action="store_true", help="Exit nonzero on regression")
    p.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    report = asyncio.run(_run(args.spec, args.server, args.token, args.model, args.project_id))

    baseline = load_baseline(args.spec, args.history_dir) if args.compare_baseline else None
    if baseline is not None:
        delta = diff_against_baseline(report, baseline)
        report["baseline"] = {
            "generated_at": baseline.get("generated_at"),
            "pass_rate": baseline.get("pass_rate"),
            **delta,
        }

    out = write_report(report, args.history_dir)
    log.info(
        "wrote %s | pass %d/%d (%.1f%%)",
        out,
        report["counts"]["pass"],
        report["counts"]["total"],
        100 * report["pass_rate"],
    )

    if args.compare_baseline and baseline is not None:
        regressions = report["baseline"]["regressions"]
        if regressions or report["baseline"]["pass_rate_delta"] < -REGRESSION_THRESHOLD:
            log.error(
                "REGRESSION vs baseline: %d specs pass→fail, pass_rate delta %+.2f",
                len(regressions),
                report["baseline"]["pass_rate_delta"],
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
