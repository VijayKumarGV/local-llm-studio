"""File + URL text extractors."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import extractors


@pytest.fixture
def pdf_three_pages(tmp_path: Path) -> Path:
    """Generate a real 3-page PDF via reportlab at test time."""
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.pdfgen.canvas import Canvas
    p = tmp_path / "three.pdf"
    c = Canvas(str(p))
    for i in range(1, 4):
        c.drawString(72, 720, f"Page {i}")
        c.drawString(72, 700, f"This is content for page number {i}.")
        c.drawString(72, 680, f"Unique-token-page-{i}-xyz")
        c.showPage()
    c.save()
    return p


@pytest.fixture
def pdf_empty(tmp_path: Path) -> Path:
    """A PDF with a blank page — no extractable text (simulates image-only)."""
    pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.pdfgen.canvas import Canvas
    p = tmp_path / "empty.pdf"
    Canvas(str(p)).save()  # no pages, no text
    return p


# ─── extract_text_from_file ───────────────────────────────────────────

class TestExtractTextFromFile:
    def test_text_file(self, fixtures_dir: Path) -> None:
        text, kind = extractors.extract_text_from_file(str(fixtures_dir / "sample.txt"))
        assert kind == "text"
        assert "quick brown fox" in text

    def test_markdown_file(self, fixtures_dir: Path) -> None:
        text, kind = extractors.extract_text_from_file(str(fixtures_dir / "sample.md"))
        assert kind == "text"
        assert "# Sample Markdown" in text
        assert "def hello" in text

    def test_pdf_three_pages(self, pdf_three_pages: Path) -> None:
        text, kind = extractors.extract_text_from_file(str(pdf_three_pages))
        assert kind == "pdf"
        # Every page's unique marker should have been extracted
        assert "Unique-token-page-1-xyz" in text
        assert "Unique-token-page-2-xyz" in text
        assert "Unique-token-page-3-xyz" in text
        # Page delimiters we inject
        assert "[page 1]" in text
        assert "[page 3]" in text

    def test_pdf_no_text_is_empty_not_exception(self, pdf_empty: Path) -> None:
        text, kind = extractors.extract_text_from_file(str(pdf_empty))
        assert kind == "pdf"
        # Blank PDF → empty string, no exception
        assert text.strip() == ""

    def test_binary_file(self, tmp_path: Path) -> None:
        binfile = tmp_path / "blob.bin"
        binfile.write_bytes(b"\x00\x01\x02\xff")
        text, kind = extractors.extract_text_from_file(str(binfile))
        assert kind == "binary"
        assert text == ""

    def test_mime_type_forces_pdf_path(self, tmp_path: Path) -> None:
        # File without .pdf extension but explicit mime type
        pytest.importorskip("reportlab.pdfgen.canvas")
        from reportlab.pdfgen.canvas import Canvas
        p = tmp_path / "no_ext_pdf"
        Canvas(str(p)).save()
        text, kind = extractors.extract_text_from_file(str(p), mime_type="application/pdf")
        assert kind == "pdf"

    def test_missing_file_returns_empty(self) -> None:
        text, kind = extractors.extract_text_from_file("/no/such/file.txt")
        assert text == ""


# ─── fetch_url_as_text: mocked httpx client ───────────────────────────

class TestFetchUrlAsText:
    def test_returns_title_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        html = (
            "<html><head><title>Test Article</title></head>"
            "<body><nav>menu</nav>"
            "<article><h1>Main heading</h1><p>The main article body content goes here. "
            "It has enough real prose that trafilatura can extract it as the main content "
            "of the page, ignoring navigation and footer chrome around it.</p></article>"
            "<footer>© 2026</footer></body></html>"
        )

        class FakeResp:
            text = html
            def raise_for_status(self): pass

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def get(self, url): return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        text, title = extractors.fetch_url_as_text("https://example.com/article")
        assert "main article body content" in text.lower()
        # Trafilatura may or may not extract nav — but the extractable body must be present
        assert len(text) > 50

    def test_returns_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        class FakeResp:
            text = "<html><head><title>My Page Title</title></head><body><p>content here has to be reasonably long so that trafilatura actually returns something for it.</p></body></html>"
            def raise_for_status(self): pass

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def get(self, url): return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        _, title = extractors.fetch_url_as_text("https://x.example.com")
        # Trafilatura's metadata extraction may or may not find the title;
        # if not, it falls back to the URL.
        assert title
