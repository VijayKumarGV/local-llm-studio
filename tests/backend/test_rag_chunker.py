"""Chunker + heading-tracker unit tests. Kept pure — no DB, no ollama."""

from __future__ import annotations

from backend import rag


class TestExtractHeadings:
    def test_finds_all_markdown_headings(self) -> None:
        text = "# H1\n\nsome body\n\n## H2\n\nmore body\n\n### H3\n"
        got = rag._extract_headings(text)
        titles = [t for _, t in got]
        assert titles == ["H1", "H2", "H3"]

    def test_ignores_hash_not_at_line_start(self) -> None:
        text = "some #not-a-heading in the middle\n# real\n"
        titles = [t for _, t in rag._extract_headings(text)]
        assert titles == ["real"]


class TestHeadingAt:
    def test_returns_most_recent_heading(self) -> None:
        headings = [(0, "First"), (100, "Second"), (200, "Third")]
        assert rag._heading_at(headings, 50) == "First"
        assert rag._heading_at(headings, 150) == "Second"
        assert rag._heading_at(headings, 999) == "Third"

    def test_empty_headings_returns_empty(self) -> None:
        assert rag._heading_at([], 42) == ""


class TestChunkWithHeadings:
    def test_empty_input_returns_empty(self) -> None:
        assert rag._chunk_with_headings("", "f.md") == []
        assert rag._chunk_with_headings("   \n\n  ", "f.md") == []

    def test_small_doc_becomes_single_chunk(self) -> None:
        text = "# Only\n\nBody paragraph one.\n\nBody paragraph two."
        chunks = rag._chunk_with_headings(text, "sample.md")
        assert len(chunks) == 1
        assert chunks[0]["heading"] == "Only"

    def test_large_doc_hard_splits_with_overlap(self) -> None:
        # ~10× the chunk target of one giant paragraph → forced hard-split.
        body = ("word " * 8000).strip()
        text = f"# Big\n\n{body}"
        chunks = rag._chunk_with_headings(text, "big.md")
        assert len(chunks) >= 2
        # All hard-split chunks under the heading.
        assert all(c["heading"] == "Big" for c in chunks)
        # Every chunk stays within the size target.
        assert all(len(c["text"]) <= rag.CHUNK_TARGET_CHARS for c in chunks)

    def test_heading_shifts_across_chunks(self) -> None:
        # Two ~CHUNK_TARGET_CHARS blocks each ensures the buffer must flush
        # under the first heading before the second heading's block starts,
        # so both headings should show up in the chunk metadata.
        block = ("filler paragraph " * 220).strip() + "\n\n"
        text = f"# First\n\n{block}## Second\n\n{block}"
        chunks = rag._chunk_with_headings(text, "shift.md")
        headings = {c["heading"] for c in chunks}
        assert "First" in headings
        assert "Second" in headings
