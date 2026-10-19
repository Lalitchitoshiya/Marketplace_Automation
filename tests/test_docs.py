from pathlib import Path

import pytest

from mta.intake.docs import DocumentError, extract_text, index_command_mentions
from tests.conftest import make_docx, make_pdf


def test_extract_txt_md_html(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("plain text", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Title\nrun **FOO**", encoding="utf-8")
    (tmp_path / "c.html").write_text(
        "<html><head><style>.x{}</style><script>alert(1)</script></head>"
        "<body><p>Type ACME_X</p><p>second</p></body></html>",
        encoding="utf-8",
    )
    assert extract_text(tmp_path / "a.txt") == "plain text"
    assert "run **FOO**" in extract_text(tmp_path / "b.md")
    html = extract_text(tmp_path / "c.html")
    assert "Type ACME_X" in html and "second" in html
    assert "alert" not in html and ".x{}" not in html


def test_extract_docx(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "guide.docx", ["Hello", "Type ACME_DIMALL now"])
    assert extract_text(path).splitlines() == ["Hello", "Type ACME_DIMALL now"]


def test_extract_pdf(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "guide.pdf", "Run ACME_EXPORTCSV to export")
    assert "ACME_EXPORTCSV" in extract_text(path)


def test_broken_documents_raise_document_error(tmp_path: Path) -> None:
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf at all")
    (tmp_path / "broken.docx").write_bytes(b"not a zip")
    (tmp_path / "x.rtf").write_text("x", encoding="utf-8")
    for name in ("broken.pdf", "broken.docx", "x.rtf"):
        with pytest.raises(DocumentError):
            extract_text(tmp_path / name)


def test_command_mention_index() -> None:
    texts = {
        "guide.docx": "Type DIMALL and press Enter.\nUse ACME_EXPORTCSV for CSV.\nSee the PDF and HTML docs.",
        "notes.md": "The command: RENUMBER updates tags.\nAlso try LINEX.",
    }
    index = index_command_mentions(texts, known={"linex"})
    assert set(index) == {"DIMALL", "ACME_EXPORTCSV", "RENUMBER", "LINEX"}  # not PDF / HTML
    mention = index["ACME_EXPORTCSV"][0]
    assert (mention.document, mention.line) == ("guide.docx", 2)
    assert mention.snippet == "Use ACME_EXPORTCSV for CSV."
