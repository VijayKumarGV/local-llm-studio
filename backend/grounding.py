"""
Grounding / hallucination check.

For each sentence in the assistant's response, compute the max cosine
similarity to any retrieved RAG chunk. Sentences with low support are
flagged as potentially unsupported.

Runs only when RAG actually returned chunks. Silent no-op otherwise.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from backend.rag import _cosine, _current_model, _embed_batch

DEFAULT_THRESHOLD = 0.55  # cosine below this = unsupported
MIN_SENTENCE_CHARS = 20  # ignore trivial fragments


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = _SENT_RE.split(text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_SENTENCE_CHARS]


async def check(
    response_text: str,
    chunk_texts: list[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Return per-sentence support + summary counts. Empty result if RAG
    wasn't used or the response has no substantive sentences."""
    if not chunk_texts:
        return {"status": "skipped", "reason": "no RAG chunks"}
    sentences = split_sentences(response_text)
    if not sentences:
        return {"status": "skipped", "reason": "no substantive sentences"}

    model = _current_model()
    try:
        sent_vecs = await _embed_batch(sentences, model)
        chunk_vecs = await _embed_batch(chunk_texts, model)
    except Exception as e:
        return {"status": "error", "error": f"embedding failed: {e}"}

    if not sent_vecs or not chunk_vecs:
        return {"status": "skipped", "reason": "empty embeddings"}

    chunk_mat = np.stack(chunk_vecs)
    results = []
    supported = 0
    for sent, svec in zip(sentences, sent_vecs, strict=True):
        sims = _cosine(chunk_mat, svec)
        best = float(np.max(sims))
        is_supported = best >= threshold
        if is_supported:
            supported += 1
        results.append(
            {
                "sentence": sent[:200],
                "max_similarity": round(best, 3),
                "supported": is_supported,
            }
        )
    total = len(results)
    return {
        "status": "success",
        "supported": supported,
        "total": total,
        "coverage": round(supported / total, 3) if total else 0.0,
        "threshold": threshold,
        "sentences": results,
    }
