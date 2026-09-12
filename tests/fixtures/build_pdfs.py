"""One-shot script to (re)build the PDF test fixtures via reportlab.

Not part of the test suite — the tests generate PDFs into a tmp_path on the
fly. This script exists so the fixtures can be committed alongside the .txt
and .md if we ever want deterministic files under tests/fixtures/.

Run: .venv/bin/python tests/fixtures/build_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent


def build_three_page_text_pdf(path: Path) -> None:
    c = Canvas(str(path))
    for i in range(1, 4):
        c.drawString(72, 720, f"Page {i}")
        c.drawString(72, 700, f"This is content for page number {i}.")
        c.drawString(72, 680, f"Unique-token-page-{i}-xyz")
        c.showPage()
    c.save()


def build_empty_pdf(path: Path) -> None:
    c = Canvas(str(path))
    c.showPage()  # blank page — no drawString calls → no text
    c.save()


if __name__ == "__main__":
    build_three_page_text_pdf(HERE / "sample_3page.pdf")
    build_empty_pdf(HERE / "sample_empty.pdf")
    print(f"wrote fixtures under {HERE}")
