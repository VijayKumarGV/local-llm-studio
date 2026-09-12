"""
File and URL text extractors for Local LLM Studio.

Given a file path (any type) or a URL, return clean UTF-8 text ready for
RAG chunking. Falls back gracefully — an image-only PDF returns "" rather
than raising, so ingestion just skips it.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

log = logging.getLogger("studio.extractors")

TEXT_EXTS = {
    ".txt", ".md", ".mdx", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".css", ".json", ".csv", ".xml", ".yaml", ".yml",
    ".sql", ".sh", ".bash", ".rb", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".swift", ".kt", ".php", ".ini", ".toml", ".conf",
    ".log", ".env",
}
PDF_EXTS = {".pdf"}


def _read_text_file(path: str, max_chars: Optional[int] = None) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_chars) if max_chars else fh.read()
    except Exception as e:
        log.warning("read_text_file failed: %s", e)
        return ""


def _read_pdf(path: str, max_pages: int = 500) -> str:
    """Extract text from a PDF. Returns empty string if PDF is image-only or
    parsing fails."""
    try:
        from pypdf import PdfReader
    except Exception as e:
        log.warning("pypdf import failed: %s", e)
        return ""
    try:
        reader = PdfReader(path)
        pages = reader.pages[:max_pages]
        parts = []
        for i, page in enumerate(pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            text = text.strip()
            if text:
                parts.append(f"[page {i}]\n{text}")
        return "\n\n".join(parts)
    except Exception as e:
        log.warning("read_pdf failed on %s: %s", path, e)
        return ""


def extract_text_from_file(path: str, mime_type: str = "") -> Tuple[str, str]:
    """Return (extracted_text, kind) where kind is one of: text|pdf|binary."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXTS or mime_type == "application/pdf":
        return _read_pdf(path), "pdf"
    if ext in TEXT_EXTS or (mime_type and "text" in mime_type):
        return _read_text_file(path), "text"
    return "", "binary"


def fetch_url_as_text(url: str, timeout: float = 15.0) -> Tuple[str, str]:
    """Fetch a web page and return (clean_text, page_title). Uses trafilatura
    for main-content extraction (strips nav/ads/footers)."""
    import httpx
    try:
        import trafilatura
    except Exception as e:
        raise RuntimeError(f"trafilatura not available: {e}") from e

    with httpx.Client(timeout=timeout, follow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    }) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    # trafilatura returns None if it can't find content
    body = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True) or ""
    # metadata for title
    try:
        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta and meta.title else url) if meta else url
    except Exception:
        title = url
    return body.strip(), title.strip()
