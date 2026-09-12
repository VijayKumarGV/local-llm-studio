"""
RAG pipeline for Local LLM Studio.

Retrieval is **hybrid**: FTS5 BM25 keyword rank + `nomic-embed-text` cosine
similarity, fused by Reciprocal Rank Fusion (RRF). Keyword search catches
exact tokens like "T1055" and unusual identifiers; vector search catches
paraphrase. Together they beat either one alone.

Chunks are header-aware — the embedded text and stored text both start with
`[filename › first-heading]` so retrieval and citations know what section
each chunk belongs to.

Embeddings are stored as float32 BLOBs in SQLite; the top-k cosine scan is
in-Python via numpy. FTS5 provides the BM25 side natively.

Silently no-ops if the embedding model isn't pulled — features degrade
gracefully instead of failing loud.
"""

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any

import httpx
import numpy as np

from backend import database
from backend.ollama_client import get_ollama_client

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_HYDE_MODEL = "llama3.2:1b"  # fast; only writes a short hypothetical answer
DEFAULT_RERANK_MODEL = "dolphin3:latest"  # 8B — good instruction following, fast enough for rerank
CHUNK_TARGET_CHARS = 3200
CHUNK_OVERLAP_CHARS = 400
MAX_CHUNKS_PER_FILE = 200
RRF_K = 60  # reciprocal-rank-fusion constant; 60 is the classic value
MMR_LAMBDA = 0.5  # 0 = pure diversity, 1 = pure relevance
RERANK_POOL = 20  # how many top candidates the LLM reranker considers
HYDE_TIMEOUT_S = 15
RERANK_TIMEOUT_S = 20


# ==========================================
# SCHEMA
# ==========================================


def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_chunks (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                conversation_id TEXT,
                project_id TEXT,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB,
                embedding_model TEXT,
                dim INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_chunks_file ON file_chunks(file_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_chunks_conv ON file_chunks(conversation_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file_chunks_proj ON file_chunks(project_id);")

        # FTS5 keyword index over chunk text — BM25 ranking is built in.
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(
                text,
                chunk_id UNINDEXED,
                conversation_id UNINDEXED,
                project_id UNINDEXED,
                tokenize = 'porter unicode61 remove_diacritics 2'
            );
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS file_chunks_fts_ai AFTER INSERT ON file_chunks BEGIN
                INSERT INTO file_chunks_fts(text, chunk_id, conversation_id, project_id)
                VALUES (new.text, new.id, new.conversation_id, new.project_id);
            END;
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS file_chunks_fts_ad AFTER DELETE ON file_chunks BEGIN
                DELETE FROM file_chunks_fts WHERE chunk_id = old.id;
            END;
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS file_chunks_fts_au AFTER UPDATE OF text ON file_chunks BEGIN
                DELETE FROM file_chunks_fts WHERE chunk_id = old.id;
                INSERT INTO file_chunks_fts(text, chunk_id, conversation_id, project_id)
                VALUES (new.text, new.id, new.conversation_id, new.project_id);
            END;
        """)
        conn.commit()

        # Backfill FTS index if chunks exist but weren't in FTS (first-run after upgrade).
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM file_chunks")
        n_chunks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM file_chunks_fts")
        n_fts = cur.fetchone()[0]
        if n_chunks > 0 and n_fts < n_chunks:
            cur.execute(
                "INSERT INTO file_chunks_fts(text, chunk_id, conversation_id, project_id) "
                "SELECT text, id, conversation_id, project_id FROM file_chunks "
                "WHERE id NOT IN (SELECT chunk_id FROM file_chunks_fts)"
            )
            conn.commit()


# ==========================================
# CHUNKING
# ==========================================

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _extract_headings(text: str) -> list[tuple[int, str]]:
    """Return list of (char_offset, heading_title) for markdown headings."""
    out = []
    for m in _HEADING_RE.finditer(text):
        out.append((m.start(), m.group(2).strip()))
    return out


def _heading_at(headings: list[tuple[int, str]], offset: int) -> str:
    """Return the most recent heading at or before `offset`, or ''."""
    last = ""
    for off, title in headings:
        if off <= offset:
            last = title
        else:
            break
    return last


def _hard_split(text: str, headings: list[tuple[int, str]], base_offset: int) -> list[dict[str, Any]]:
    """Blindly split `text` into CHUNK_TARGET_CHARS-sized pieces with overlap."""
    out: list[dict[str, Any]] = []
    step = max(CHUNK_TARGET_CHARS - CHUNK_OVERLAP_CHARS, 1)
    for i in range(0, len(text), step):
        piece = text[i : i + CHUNK_TARGET_CHARS]
        if not piece.strip():
            continue
        heading = _heading_at(headings, base_offset + i)
        out.append({"text": piece, "heading": heading})
    return out


def _chunk_with_headings(text: str, filename: str) -> list[dict[str, Any]]:
    """Chunk text and annotate each chunk with the enclosing markdown heading.

    Two-stage strategy:
      1. Split on blank-line paragraph boundaries.
      2. Any paragraph (or accumulated buffer) that still exceeds
         CHUNK_TARGET_CHARS gets hard-split with overlap — this handles docs
         (RFCs, scraped HTML) that have newlines but no blank-line breaks.
    """
    text = text.strip()
    if not text:
        return []
    headings = _extract_headings(text)
    paragraphs = re.split(r"\n\s*\n", text)
    out: list[dict[str, Any]] = []
    buf = ""
    buf_offset = 0
    cursor = 0

    def _flush(buf_text: str, offset: int):
        if not buf_text.strip():
            return
        if len(buf_text) <= CHUNK_TARGET_CHARS:
            out.append({"text": buf_text, "heading": _heading_at(headings, offset)})
        else:
            out.extend(_hard_split(buf_text, headings, offset))

    for p in paragraphs:
        p = p.strip()
        if not p:
            cursor += 2
            continue
        p_offset = text.find(p, cursor)
        if p_offset < 0:
            p_offset = cursor
        cursor = p_offset + len(p)

        if len(buf) + len(p) + 2 <= CHUNK_TARGET_CHARS:
            if not buf:
                buf_offset = p_offset
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            _flush(buf, buf_offset)
            # Start new buffer from this paragraph. If it's already huge, flush
            # immediately via hard-split; otherwise let it accumulate.
            if len(p) > CHUNK_TARGET_CHARS:
                _flush(p, p_offset)
                buf = ""
            else:
                buf = p
                buf_offset = p_offset

    _flush(buf, buf_offset)
    return out


def _annotate(chunk_text: str, filename: str, heading: str) -> str:
    """Prepend `[filename › heading]` to chunk text — improves both semantic
    retrieval (embedding sees the context) and BM25 (filename/heading tokens
    are searchable)."""
    prefix = f"[{filename} › {heading}]" if heading else f"[{filename}]"
    if chunk_text.startswith(prefix):
        return chunk_text
    return f"{prefix}\n\n{chunk_text}"


# ==========================================
# EMBEDDINGS
# ==========================================


async def _embed_batch(texts: list[str], model: str, batch_size: int = 32) -> list[np.ndarray]:
    """Batch embed via Ollama's newer /api/embed endpoint (falls back to per-item)."""
    client = get_ollama_client()
    out: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        try:
            resp = await client.post(
                "/api/embed",
                json={"model": model, "input": chunk},
                timeout=120.0,
            )
            resp.raise_for_status()
            embeddings = (resp.json() or {}).get("embeddings") or []
            if not embeddings:
                raise RuntimeError(f"Empty batch embeddings for model {model!r}")
            for vec_list in embeddings:
                out.append(np.asarray(vec_list, dtype=np.float32))
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            for t in chunk:
                r = await client.post(
                    "/api/embeddings",
                    json={"model": model, "prompt": t},
                    timeout=60.0,
                )
                r.raise_for_status()
                vec = np.asarray(r.json().get("embedding") or [], dtype=np.float32)
                if vec.size == 0:
                    raise RuntimeError(f"Empty embedding for model {model!r}") from None
                out.append(vec)
    return out


def _current_model() -> str:
    return database.get_settings().get("embedding_model") or DEFAULT_EMBED_MODEL


def _setting_bool(key: str, default: bool = True) -> bool:
    v = database.get_settings().get(key)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


# ==========================================
# HyDE — Hypothetical Document Embedding
# ==========================================

_HYDE_SYSTEM = (
    "You are a search-query rewriter. Given a user question, write a plausible "
    "short passage (2-3 sentences) that would appear in a technical document "
    "answering it. Include likely keywords, identifiers (like CVE-… or T####), "
    "and technical terminology. Do NOT hedge, don't preface, don't say 'I don't "
    "know'. Just write the passage. Output only the passage — no fences, no "
    "headings, no commentary."
)


async def _hyde_expand(query: str) -> str:
    """Return a hypothetical answer passage to use as the retrieval query.
    Falls back to the raw query on any failure."""
    model = database.get_settings().get("hyde_model") or DEFAULT_HYDE_MODEL
    client = get_ollama_client()
    try:
        resp = await client.post(
            "/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": _HYDE_SYSTEM},
                    {"role": "user", "content": query},
                ],
                "options": {"temperature": 0.2, "num_predict": 180},
            },
            timeout=HYDE_TIMEOUT_S,
        )
        resp.raise_for_status()
        text = (resp.json().get("message") or {}).get("content", "").strip()
        # Guard against models that echo the question or refuse
        if len(text) < 40 or text.lower().startswith(("i don't", "i cannot", "sorry")):
            return query
        return f"{query}\n\n{text}"
    except Exception:
        return query


# ==========================================
# LLM Reranker
# ==========================================

_RERANK_SYSTEM = (
    "You are a relevance judge. Given a user query and numbered snippets, "
    "score each snippet from 0 to 10 for how well it answers the query "
    "(10 = directly answers, 0 = irrelevant). Return ONLY a JSON object of "
    'exactly this shape: {"scores": [{"id": 1, "score": 8}, ...]}. No preamble.'
)


async def _llm_rerank(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask a fast model to score relevance; sort by score. Returns re-ordered
    candidates. On any failure, returns candidates unchanged."""
    if len(candidates) <= 1:
        return candidates
    model = database.get_settings().get("rerank_model") or DEFAULT_RERANK_MODEL
    client = get_ollama_client()

    # Truncate each snippet so the whole rerank prompt stays small
    numbered = []
    for i, c in enumerate(candidates, start=1):
        snippet = (c.get("text") or "").replace("\n", " ")[:280]
        numbered.append(f"[{i}] {snippet}")
    prompt = f"QUERY: {query}\n\nSNIPPETS:\n" + "\n\n".join(numbered)

    try:
        resp = await client.post(
            "/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": _RERANK_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.0, "num_predict": 400},
                "format": "json",
            },
            timeout=RERANK_TIMEOUT_S,
        )
        resp.raise_for_status()
        raw = (resp.json().get("message") or {}).get("content", "")
        data = json.loads(raw) if raw.strip().startswith("{") else {}
        scores = data.get("scores") or []
        # Build id -> score map (1-indexed as we sent it)
        score_by_id: dict[int, float] = {}
        for s in scores:
            try:
                score_by_id[int(s["id"])] = float(s["score"])
            except (KeyError, ValueError, TypeError):
                continue
        if not score_by_id:
            return candidates
        # Attach scores and sort; unscored candidates get 0
        for i, c in enumerate(candidates, start=1):
            c["rerank_score"] = score_by_id.get(i, 0.0)
        candidates.sort(key=lambda x: -x.get("rerank_score", 0.0))
        return candidates
    except Exception:
        return candidates


# ==========================================
# MMR — Maximal Marginal Relevance
# ==========================================


def _mmr(
    candidates: list[dict[str, Any]],
    embeddings: dict[str, np.ndarray],
    query_vec: np.ndarray,
    top_k: int,
    lam: float = MMR_LAMBDA,
) -> list[dict[str, Any]]:
    """Iteratively pick the candidate maximizing:
        lam * relevance(q, d) - (1-lam) * max_similarity(d, already_picked)
    so top_k spans diverse chunks instead of concentrating in one file."""
    if len(candidates) <= top_k:
        return candidates
    remaining = list(candidates)
    picked: list[dict[str, Any]] = []

    def _sim(a: np.ndarray, b: np.ndarray) -> float:
        return float((a @ b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))

    # Precompute query similarity for every candidate
    rel = {c["id"]: _sim(embeddings[c["id"]], query_vec) if c["id"] in embeddings else 0.0 for c in remaining}

    while remaining and len(picked) < top_k:
        best = None
        best_score = -float("inf")
        for c in remaining:
            r = rel.get(c["id"], 0.0)
            if picked and c["id"] in embeddings:
                max_sim = max(_sim(embeddings[c["id"]], embeddings[p["id"]]) for p in picked if p["id"] in embeddings)
            else:
                max_sim = 0.0
            score = lam * r - (1 - lam) * max_sim
            if score > best_score:
                best_score = score
                best = c
        picked.append(best)
        remaining.remove(best)
    return picked


# ==========================================
# INGEST
# ==========================================


async def ingest_file(file_id: str, text: str | None = None, force: bool = False) -> dict[str, Any]:
    """Chunk + embed a file with header-aware annotation. Skips if already
    indexed under the current embedding model (unless force=True)."""
    ensure_schema()
    rec = database.get_file(file_id)
    if not rec:
        return {"status": "error", "error": "file not found"}

    if not force:
        expected_model = _current_model()
        with database.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM file_chunks WHERE file_id = ? AND embedding_model = ?",
                (file_id, expected_model),
            )
            existing = cur.fetchone()[0]
        if existing > 0:
            return {"status": "skipped", "chunks": existing, "reason": "already indexed"}

    # Prefer explicit text > full disk read > stored preview.
    # The stored extracted_text is truncated to 4000 chars for the DB row,
    # so re-ingest must read the full file from disk to see everything.
    if text is not None:
        body = text
    else:
        body = ""
        fp = rec.get("filepath")
        if fp and os.path.exists(fp):
            # For PDFs, re-extract from the raw file.
            if fp.lower().endswith(".pdf"):
                from backend import extractors

                body, _ = extractors.extract_text_from_file(fp, "application/pdf")
            else:
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as fh:
                        body = fh.read()
                except Exception:
                    body = ""
        if not body:
            body = rec.get("extracted_text") or ""

    filename = rec.get("filename") or "unknown"
    chunks_meta = _chunk_with_headings(body, filename)
    if not chunks_meta:
        return {"status": "empty", "chunks": 0}
    if len(chunks_meta) > MAX_CHUNKS_PER_FILE:
        return {
            "status": "skipped",
            "chunks": 0,
            "reason": f"file too large ({len(chunks_meta)} chunks > cap {MAX_CHUNKS_PER_FILE})",
        }

    annotated = [_annotate(c["text"], filename, c["heading"]) for c in chunks_meta]

    model = _current_model()
    try:
        vectors = await _embed_batch(annotated, model)
    except Exception as e:
        return {"status": "error", "error": f"embedding failed: {e}"}

    now = datetime.now().isoformat()
    with database.get_connection() as conn:
        conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
        for i, (ann_text, vec) in enumerate(zip(annotated, vectors, strict=True)):
            conn.execute(
                "INSERT INTO file_chunks (id, file_id, conversation_id, project_id, chunk_index, text, embedding, embedding_model, dim, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    file_id,
                    rec.get("conversation_id"),
                    rec.get("project_id"),
                    i,
                    ann_text,
                    vec.tobytes(),
                    model,
                    int(vec.size),
                    now,
                ),
            )
        conn.commit()
    return {"status": "success", "chunks": len(annotated), "model": model}


# ==========================================
# RETRIEVAL — HYBRID (VECTOR + BM25) VIA RRF
# ==========================================


def _cosine(mat: np.ndarray, q: np.ndarray) -> np.ndarray:
    denom = (np.linalg.norm(mat, axis=1) * np.linalg.norm(q)) + 1e-9
    return (mat @ q) / denom


def _fts_query(raw: str) -> str:
    """Quote each token so FTS5 treats them literally (no operator parsing on
    user input)."""
    toks = [t.replace('"', '""') for t in raw.split() if t]
    return " ".join(f'"{t}"' for t in toks) if toks else '""'


async def retrieve(
    query: str,
    conversation_id: str | None = None,
    project_id: str | None = None,
    top_k: int = 6,
    candidates_per_source: int = 30,
    use_hyde: bool | None = None,
    use_reranker: bool | None = None,
    use_mmr: bool | None = None,
) -> list[dict[str, Any]]:
    """Hybrid retrieval with three quality upgrades:
        1. HyDE: expand the query with a hypothetical answer before embedding.
        2. Hybrid RRF: fuse vector top-N and BM25 top-N.
        3. LLM rerank: fast model scores top-20 candidates.
        4. MMR: pick top_k that maximize relevance AND diversity.
    Each stage is opt-in via settings (use_hyde / use_reranker / use_mmr,
    all default on)."""
    ensure_schema()
    if not query.strip():
        return []

    # Resolve per-call overrides against settings (default all on)
    if use_hyde is None:
        use_hyde = _setting_bool("use_hyde", True)
    if use_reranker is None:
        use_reranker = _setting_bool("use_reranker", True)
    if use_mmr is None:
        use_mmr = _setting_bool("use_mmr", True)

    # Cross-workspace: when on, drop the project scope entirely so the query
    # searches every workspace at once. Useful when the user isn't sure which
    # workspace the answer lives in.
    cross_ws = _setting_bool("cross_workspace_retrieval", False)
    if not (conversation_id or project_id) and not cross_ws:
        return []

    embed_query = query
    if use_hyde:
        embed_query = await _hyde_expand(query)

    scope_where: list[str] = []
    scope_params: list[Any] = []
    if cross_ws:
        # No scope filter — search everywhere. Still constrained by embedding IS NOT NULL below.
        scope_where.append("1=1")
    elif conversation_id and project_id:
        scope_where.append("(fc.conversation_id = ? OR fc.project_id = ?)")
        scope_params += [conversation_id, project_id]
    elif conversation_id:
        scope_where.append("fc.conversation_id = ?")
        scope_params.append(conversation_id)
    elif project_id:
        scope_where.append("fc.project_id = ?")
        scope_params.append(project_id)

    # --- 1. Vector candidates ---
    vector_rank: dict[str, int] = {}
    vector_scores: dict[str, float] = {}
    with database.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT fc.id, fc.file_id, fc.chunk_index, fc.text, fc.embedding, fc.dim, f.filename "
            f"FROM file_chunks fc LEFT JOIN files f ON f.id = fc.file_id "
            f"WHERE fc.embedding IS NOT NULL AND {' AND '.join(scope_where)}",
            scope_params,
        )
        rows = cur.fetchall()
    row_by_id: dict[str, sqlite3.Row] = {r["id"]: r for r in rows}

    embeddings_by_id: dict[str, np.ndarray] = {}
    qvec: np.ndarray | None = None
    if rows:
        dim = rows[0]["dim"]
        rows = [r for r in rows if r["dim"] == dim]
        model = _current_model()
        try:
            qvec = (await _embed_batch([embed_query], model))[0]
        except Exception:
            qvec = None
        if qvec is not None and qvec.size == dim:
            mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            scores = _cosine(mat, qvec)
            order = np.argsort(-scores)[:candidates_per_source]
            for rank, idx in enumerate(order):
                cid = rows[idx]["id"]
                vector_rank[cid] = rank + 1
                vector_scores[cid] = float(scores[idx])
                embeddings_by_id[cid] = mat[idx]

    # --- 2. BM25 (FTS5) candidates ---
    bm25_rank: dict[str, int] = {}
    bm25_scores: dict[str, float] = {}
    fts_where: list[str] = ["file_chunks_fts MATCH ?"]
    fts_params: list[Any] = [_fts_query(query)]
    if cross_ws:
        pass  # no scope
    elif conversation_id and project_id:
        fts_where.append("(file_chunks_fts.conversation_id = ? OR file_chunks_fts.project_id = ?)")
        fts_params += [conversation_id, project_id]
    elif conversation_id:
        fts_where.append("file_chunks_fts.conversation_id = ?")
        fts_params.append(conversation_id)
    elif project_id:
        fts_where.append("file_chunks_fts.project_id = ?")
        fts_params.append(project_id)
    fts_params.append(candidates_per_source)

    try:
        with database.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT chunk_id, rank FROM file_chunks_fts WHERE {' AND '.join(fts_where)} ORDER BY rank LIMIT ?",
                fts_params,
            )
            for rank, row in enumerate(cur.fetchall()):
                cid = row["chunk_id"]
                bm25_rank[cid] = rank + 1
                bm25_scores[cid] = float(row["rank"])  # negative BM25 (lower = better in fts5)
    except sqlite3.OperationalError:
        # FTS syntax error on the query (e.g., only punctuation) — skip BM25.
        pass

    # --- 3. Reciprocal-Rank Fusion ---
    fused: dict[str, float] = {}
    for cid, r in vector_rank.items():
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + r)
    for cid, r in bm25_rank.items():
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + r)

    # Take a wider pool first — reranker and MMR both need candidates to work with.
    pool_size = max(top_k, RERANK_POOL if use_reranker else top_k * 3)
    ranked = sorted(fused.items(), key=lambda kv: -kv[1])[:pool_size]

    # If a BM25-only chunk landed in the pool, we need its row too.
    missing = [cid for cid, _ in ranked if cid not in row_by_id]
    if missing:
        placeholders = ",".join("?" for _ in missing)
        with database.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT fc.id, fc.file_id, fc.chunk_index, fc.text, f.filename "
                f"FROM file_chunks fc LEFT JOIN files f ON f.id = fc.file_id "
                f"WHERE fc.id IN ({placeholders})",
                missing,
            )
            for r in cur.fetchall():
                row_by_id[r["id"]] = r

    pool: list[dict[str, Any]] = []
    for cid, fused_score in ranked:
        r = row_by_id.get(cid)
        if not r:
            continue
        pool.append(
            {
                "id": cid,
                "file_id": r["file_id"],
                "chunk_index": int(r["chunk_index"]),
                "text": r["text"],
                "filename": r["filename"],
                "score": round(fused_score, 6),
                "vector_score": round(vector_scores.get(cid, 0.0), 4),
                "bm25_rank": bm25_rank.get(cid),
                "vector_rank": vector_rank.get(cid),
            }
        )

    # LLM rerank the fused pool
    if use_reranker and len(pool) > 1:
        pool = await _llm_rerank(query, pool[:RERANK_POOL])

    # MMR diversity on final top_k
    if use_mmr and qvec is not None and len(pool) > top_k:
        pool = _mmr(pool, embeddings_by_id, qvec, top_k)
    else:
        pool = pool[:top_k]

    return pool
