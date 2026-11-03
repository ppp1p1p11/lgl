import io
import re

import docx
import pytest
from rapidfuzz.distance import Levenshtein
from reportlab.pdfgen import canvas

from legalos.documents import filetypes
from legalos.documents.extraction import ExtractionError, extract, normalize_text
from tests.corpus.generator import (
    build_corpus,
    ground_truth,
    render_docx,
    render_pdf,
    render_photo,
    render_scan,
)

DOC = build_corpus()[1]  # contestação cível, one page


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cer(expected: str, actual: str) -> float:
    return Levenshtein.distance(_norm(expected), _norm(actual)) / len(_norm(expected))


def test_sniff_detects_real_type_regardless_of_name() -> None:
    assert filetypes.sniff(render_pdf(DOC)) == "pdf"
    assert filetypes.sniff(render_photo(DOC)) == "jpeg"
    assert filetypes.sniff(render_docx(DOC)) == "docx"
    assert filetypes.sniff(b"<html><script>alert(1)</script></html>") is None
    assert filetypes.sniff(b"MZ\x90\x00 windows executable") is None
    assert filetypes.sniff(b"PK\x03\x04 not really a zip") is None


def test_digital_pdf_uses_text_layer_exactly() -> None:
    pages = extract(render_pdf(DOC), "pdf")
    assert [p.method for p in pages] == ["text_layer"]
    assert _norm(pages[0].text) == _norm(ground_truth(DOC)[0])


def test_scanned_pdf_is_ocrd_accurately() -> None:
    pages = extract(render_scan(DOC, "good"), "pdf")
    assert pages[0].method == "ocr"
    assert _cer(ground_truth(DOC)[0], pages[0].text) < 0.03
    assert pages[0].ocr_confidence is not None and pages[0].ocr_confidence > 80


def test_photo_is_ocrd() -> None:
    page = extract(render_photo(DOC), "jpeg")[0]
    assert _cer(ground_truth(DOC)[0], page.text) < 0.03


def test_unreadable_scan_is_flagged_by_low_confidence() -> None:
    page = extract(render_scan(DOC, "bad"), "pdf")[0]
    assert (page.ocr_confidence or 0) < 70


def test_docx() -> None:
    pages = extract(render_docx(DOC), "docx")
    assert len(pages) == 1 and pages[0].method == "docx"
    assert _norm(pages[0].text) == _norm(DOC.pages[0])


def test_docx_tables_are_included() -> None:
    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Valor da causa"
    table.rows[0].cells[1].text = "R$ 10.000,00"
    out = io.BytesIO()
    document.save(out)
    assert "Valor da causa | R$ 10.000,00" in extract(out.getvalue(), "docx")[0].text


def test_password_protected_pdf() -> None:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, encrypt="segredo")
    c.drawString(100, 700, "conteúdo protegido")
    c.showPage()
    c.save()
    with pytest.raises(ExtractionError) as err:
        extract(buffer.getvalue(), "pdf")
    assert err.value.code == "pdf_encrypted"


def test_corrupt_pdf() -> None:
    with pytest.raises(ExtractionError) as err:
        extract(b"%PDF-1.7 garbage that is not a pdf", "pdf")
    assert err.value.code == "pdf_unreadable"


def test_normalize_text() -> None:
    assert normalize_text("a\u00a0 b\r\n\r\n\r\n\r\nc  \x0c d\x00") == "a b\n\nc\nd"
