"""Detect a file's real type from its content. The name and the browser's declared type
are never trusted."""

import io
import zipfile

# Generous limit on a DOCX's uncompressed size, against "zip bombs".
MAX_DOCX_UNCOMPRESSED = 200 * 1024 * 1024

SUPPORTED_TYPES = ("pdf", "png", "jpeg", "docx")

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04") and _is_docx(data):
        return "docx"
    return None


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return False
    return (
        "[Content_Types].xml" in names
        and "word/document.xml" in names
        and total <= MAX_DOCX_UNCOMPRESSED
    )
