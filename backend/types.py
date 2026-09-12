"""Shared type aliases and TypedDicts for backend interfaces.

Import these from the site that produces or consumes the shape so mypy
verifies both ends. Everything here is documentation-in-code — no runtime
overhead beyond `TypedDict` (which is `dict` at runtime).
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

# ─── RAG ──────────────────────────────────────────────────────────────

ToolStatus = Literal[
    "success",
    "error",
    "timeout",
    "denied",
    "skipped",
    "blocked",
    "empty",
]


class RetrievalHit(TypedDict):
    """One chunk returned by rag.retrieve()."""

    id: str
    file_id: str
    chunk_index: int
    text: str
    filename: str
    score: float
    vector_score: float
    bm25_rank: NotRequired[int | None]
    vector_rank: NotRequired[int | None]
    rerank_score: NotRequired[float | None]


class ChunkMeta(TypedDict):
    """Internal chunk representation before annotation + embedding."""

    text: str
    heading: str


# ─── tool results ──────────────────────────────────────────────────────


class ToolResult(TypedDict, total=False):
    """Return shape shared by every agent tool. Fields are `total=False`
    because tools produce different subsets (e.g. sandbox has stdout,
    search has results, etc.)."""

    status: ToolStatus
    error: str
    stdout: str
    stderr: str
    return_code: int
    sandboxed: bool
    results: list[dict[str, Any]]
    query: str
    count: int
    artifact_id: str
    name: str
    text: str
    url: str
    title: str
    chars: int


class SandboxResult(TypedDict, total=False):
    status: ToolStatus
    return_code: int
    stdout: str
    stderr: str
    sandboxed: bool
    error: str


# ─── grounding / feedback / memory ────────────────────────────────────


class SentenceSupport(TypedDict):
    sentence: str
    max_similarity: float
    supported: bool


class GroundingReport(TypedDict, total=False):
    status: Literal["success", "skipped", "error"]
    reason: str
    error: str
    supported: int
    total: int
    coverage: float
    threshold: float
    sentences: list[SentenceSupport]


class MemoryFact(TypedDict):
    fact: str
    category: str


class MemoryRow(TypedDict):
    id: str
    fact: str
    category: str
    score: float


class FeedbackRecord(TypedDict):
    id: str
    rating: Literal[-1, 0, 1]
    note: str
    created_at: str


# ─── chat message shape (Ollama's /api/chat) ───────────────────────────


class OllamaMessage(TypedDict, total=False):
    """A single message in the payload sent to Ollama /api/chat.

    `tool_calls` and `images` are only present on turns that need them; the
    common shape is just role + content."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str  # tool result messages
    tool_calls: list[dict[str, Any]]
    images: list[str]  # base64 image data for vision models
