# ADR-0005: OCR with self-hosted Tesseract

- Status: Accepted
- Date: 2026-10-29

## Context
Many Brazilian court PDFs are scans, and photos of documents are common. Text must be
extracted before anything else (search, citations, AI) can work. Case files are
confidential, and all data at rest must stay in Brazil (brief §4). VERIFY INF-3 asked
whether a managed OCR service in São Paulo would be needed.

## Decision
- PDF pages with a usable text layer (at least 25 letters or digits) use that text
  directly: no OCR, no errors.
- Other PDF pages are rendered at 300 dpi with pdfium (`pypdfium2`, BSD/Apache) and
  read by **Tesseract 5 with the Portuguese model**, run as a separate process in the
  worker, with a 120-second limit per page. Images (JPG/PNG) go straight to Tesseract.
- Every OCR page stores Tesseract's mean word confidence (0–100). Below **70**, the UI
  warns "texto pode conter erros".
- DOCX: paragraphs and tables via `python-docx`, as one page.
- Accuracy is measured in CI on the synthetic corpus (ADR-0007): `scripts/ocr_eval.py`.

## Measurements (synthetic corpus, 2026-10-29)
| Variant | Character error rate | Confidence |
|---|---|---|
| Digital PDF, DOCX | 0% (exact) | n/a |
| Scan 200 dpi, slight skew and noise | 0–0.6% | ~96 |
| Scan 150 dpi, 1.5° skew, blur, heavy JPEG | 0–0.9% | ~95 |
| Phone-style photo | 0–0.6% | ~96 |
| Scan 100 dpi, 3° skew, strong blur (still human-readable) | 65–97% | 38–56 → flagged |

Image clean-up (sharpening, contrast) did not rescue the last case.

## Consequences
- Documents never leave our infrastructure for OCR, and there is no per-page cost.
- Ordinary scans are read almost perfectly. Very blurry low-resolution scans are not
  readable by Tesseract, but they are reliably flagged by low confidence.
- Synthetic scans are cleaner than real ones; accuracy must be re-measured on real
  anonymized PDFs from pilot firms before launch.
- Option for Phase 2b: send pages flagged as low-confidence to a vision-capable AI model
  for transcription. Only through the AI gateway, and only once the international-transfer
  question is settled (VERIFY AI-1, REG-2).
- Pages rotated 90°/180° are not auto-rotated yet (Tesseract orientation detection can be
  added if real documents need it).

## Alternatives considered
- **OCRmyPDF:** wraps Tesseract with deskew/cleanup, but adds Ghostscript and other
  system dependencies. Not needed given the measurements above.
- **Managed OCR (e.g. AWS Textract):** strong on poor scans, but its São Paulo
  availability is unverified (INF-3), and it adds per-page cost and another processor
  of client data. Revisit if real-world accuracy is poor.
