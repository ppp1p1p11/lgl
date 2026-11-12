"""Turn an uploaded file into per-page text.

- PDF pages with a usable text layer: text is read directly.
- Scanned PDF pages and images: OCR with Tesseract (Portuguese model), see ADR-0005.
- DOCX: paragraphs and tables, as a single page (Word files have no fixed pages).

All content here is untrusted input. Nothing is executed or interpreted; limits on pages,
pixels and OCR time protect the worker from hostile or broken files.
"""

import csv
import io
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import docx
import pypdfium2 as pdfium
from PIL import Image, ImageOps

MAX_PAGES = 1000
# Pages with fewer meaningful characters than this are treated as scanned.
MIN_TEXT_LAYER_CHARS = 25
OCR_DPI = 300
OCR_TIMEOUT_SECONDS = 120
OCR_LANGUAGE = "por"
# Rendered page size cap (about A3 at 300 dpi), and Pillow's own bomb protection.
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    text: str
    method: str  # "text_layer" | "ocr" | "docx"
    ocr_confidence: float | None = None


class ExtractionError(Exception):
    """A problem with the file itself. Retrying will not help."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_SPACES = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n").replace("\x00", "")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def extract(data: bytes, file_type: str) -> list[ExtractedPage]:
    if file_type == "pdf":
        return _extract_pdf(data)
    if file_type in ("png", "jpeg"):
        return [_extract_image(data)]
    if file_type == "docx":
        return [_extract_docx(data)]
    raise ExtractionError("unsupported_type")


def _extract_pdf(data: bytes) -> list[ExtractedPage]:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        code = "pdf_encrypted" if "password" in str(e).lower() else "pdf_unreadable"
        raise ExtractionError(code) from e
    try:
        if len(pdf) == 0:
            raise ExtractionError("pdf_empty")
        if len(pdf) > MAX_PAGES:
            raise ExtractionError("too_many_pages")
        pages = []
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                text = normalize_text(textpage.get_text_range())
                textpage.close()
                if _meaningful_chars(text) >= MIN_TEXT_LAYER_CHARS:
                    pages.append(ExtractedPage(index + 1, text, "text_layer"))
                    continue
                width, height = page.get_size()
                scale = OCR_DPI / 72
                if width * scale * height * scale > MAX_IMAGE_PIXELS:
                    scale = (MAX_IMAGE_PIXELS / (width * height)) ** 0.5
                image = page.render(scale=scale).to_pil()
            finally:
                page.close()
            ocr_text, confidence = ocr_image(image)
            pages.append(ExtractedPage(index + 1, ocr_text, "ocr", confidence))
        return pages
    finally:
        pdf.close()


def _extract_image(data: bytes) -> ExtractedPage:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            image = ImageOps.exif_transpose(img)
    except (OSError, Image.DecompressionBombError) as e:
        raise ExtractionError("image_unreadable") from e
    text, confidence = ocr_image(image)
    return ExtractedPage(1, text, "ocr", confidence)


def _extract_docx(data: bytes) -> ExtractedPage:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises several unrelated types for broken files
        raise ExtractionError("docx_unreadable") from e
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return ExtractedPage(1, normalize_text("\n".join(parts)), "docx")


def _meaningful_chars(text: str) -> int:
    return sum(1 for c in text if c.isalnum())


def ocr_image(image: Image.Image) -> tuple[str, float | None]:
    """OCR one image. Returns the text and the mean word confidence (0-100)."""
    gray = image.convert("L")
    with tempfile.TemporaryDirectory(prefix="legalos-ocr-") as tmp:
        source = Path(tmp) / "page.png"
        gray.save(source)
        out = Path(tmp) / "out"
        try:
            subprocess.run(  # noqa: S603 - fixed binary and arguments, no shell
                [
                    _tesseract(),
                    str(source),
                    str(out),
                    "-l",
                    OCR_LANGUAGE,
                    "--psm",
                    "3",
                    "txt",
                    "tsv",
                ],
                check=True,
                capture_output=True,
                timeout=OCR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise ExtractionError("ocr_timeout") from e
        except subprocess.CalledProcessError as e:
            raise ExtractionError("ocr_failed") from e
        text = normalize_text((Path(tmp) / "out.txt").read_text(encoding="utf-8"))
        confidence = _mean_confidence((Path(tmp) / "out.tsv").read_text(encoding="utf-8"))
    return text, confidence


@lru_cache
def _tesseract() -> str:
    path = shutil.which("tesseract")
    if path is None:
        raise RuntimeError("Tesseract is not installed (see backend/Dockerfile)")
    return path


def _mean_confidence(tsv: str) -> float | None:
    scores = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        conf, word = row.get("conf"), (row.get("text") or "").strip()
        if word and conf not in (None, "-1"):
            scores.append(float(conf))
    return round(sum(scores) / len(scores), 1) if scores else None
