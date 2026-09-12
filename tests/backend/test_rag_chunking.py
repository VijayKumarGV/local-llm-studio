"""Chunker + annotator — pure functions from rag.py, no I/O."""

from __future__ import annotations

from backend import rag


class TestExtractHeadings:
    def test_no_headings(self) -> None:
        assert rag._extract_headings("just a paragraph") == []

    def test_h1_and_h2(self) -> None:
        text = "# Title\n\nintro\n\n## Section\n\nbody"
        h = rag._extract_headings(text)
        titles = [t for _, t in h]
        assert "Title" in titles
        assert "Section" in titles

    def test_heading_at_returns_most_recent(self) -> None:
        headings = [(0, "One"), (100, "Two"), (200, "Three")]
        assert rag._heading_at(headings, 50) == "One"
        assert rag._heading_at(headings, 150) == "Two"
        assert rag._heading_at(headings, 300) == "Three"
        # Before any heading
        assert rag._heading_at(headings, -1) == ""


class TestAnnotate:
    def test_prepends_filename_and_heading(self) -> None:
        out = rag._annotate("body content", "guide.md", "Chapter 1")
        assert out.startswith("[guide.md › Chapter 1]")
        assert "body content" in out

    def test_filename_only_when_no_heading(self) -> None:
        out = rag._annotate("body", "file.md", "")
        assert out.startswith("[file.md]")
        assert "body" in out

    def test_idempotent_if_already_annotated(self) -> None:
        once = rag._annotate("text", "f.md", "h")
        twice = rag._annotate(once, "f.md", "h")
        assert once == twice


class TestChunkWithHeadings:
    def test_empty_text_returns_empty(self) -> None:
        assert rag._chunk_with_headings("", "empty.md") == []
        assert rag._chunk_with_headings("   \n\n  ", "ws.md") == []

    def test_short_text_one_chunk(self) -> None:
        chunks = rag._chunk_with_headings("hello world", "s.md")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "hello world"

    def test_paragraphs_kept_together_until_target_size(self) -> None:
        # Small paragraphs — should coalesce into one chunk
        text = "para one.\n\npara two.\n\npara three."
        chunks = rag._chunk_with_headings(text, "p.md")
        assert len(chunks) == 1

    def test_headings_recorded_per_chunk(self) -> None:
        text = "# H1\n\nintro\n\n" + ("filler. " * 500)
        chunks = rag._chunk_with_headings(text, "h.md")
        # First chunk sits under H1
        assert chunks[0]["heading"] == "H1"

    def test_giant_single_paragraph_gets_hard_split(self) -> None:
        """The RFC bug: one 300KB paragraph without blank lines used to
        emit ONE 300KB chunk. Now it should split with overlap."""
        text = "a" * 300_000
        chunks = rag._chunk_with_headings(text, "rfc.md")
        assert len(chunks) > 50  # was 1 before the fix
        assert all(len(c["text"]) <= rag.CHUNK_TARGET_CHARS for c in chunks)

    def test_hard_split_has_overlap(self) -> None:
        text = "x" * (rag.CHUNK_TARGET_CHARS * 5)
        chunks = rag._chunk_with_headings(text, "x.md")
        # Overlap means (chunks - 1) × step + last chunk ≥ len(text)
        total_content = sum(len(c["text"]) for c in chunks)
        assert total_content >= len(text)  # >= because overlap re-counts

    def test_every_chunk_bounded_by_target_size(self) -> None:
        text = ("para " * 800) + "\n\n" + ("para " * 800)
        chunks = rag._chunk_with_headings(text, "b.md")
        for c in chunks:
            assert len(c["text"]) <= rag.CHUNK_TARGET_CHARS
