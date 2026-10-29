"""OCR and text-extraction accuracy on the synthetic corpus (ADR-0005, ADR-0007).

Prints a Markdown report (CI appends it to the job summary) and exits with an error if:
- digital PDFs and DOCX are not extracted exactly,
- scans of normal quality ("good", "poor") or photos exceed 3% character error rate,
- unreadable scans ("bad") are NOT flagged as low confidence.

Usage (from backend/): uv run python scripts/ocr_eval.py
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rapidfuzz.distance import Levenshtein
from tests.corpus.generator import (
    build_corpus,
    ground_truth,
    render_docx,
    render_pdf,
    render_photo,
    render_scan,
)

from legalos.documents.extraction import extract
from legalos.documents.service import LOW_OCR_CONFIDENCE

MAX_CER = 0.03


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    failures: list[str] = []
    print("## OCR / extraction accuracy (synthetic corpus)\n")
    print("| Document | Variant | Char. error rate | Min. OCR confidence | Time |")
    print("|---|---|---|---|---|")
    for doc in build_corpus():
        full = "\n".join(ground_truth(doc))
        variants = [
            ("digital", render_pdf(doc), "pdf", full),
            ("docx", render_docx(doc), "docx", "\n".join(doc.pages)),
            ("scan good", render_scan(doc, "good"), "pdf", full),
            ("scan poor", render_scan(doc, "poor"), "pdf", full),
            ("photo", render_photo(doc), "jpeg", ground_truth(doc)[0]),
            ("scan bad", render_scan(doc, "bad"), "pdf", full),
        ]
        for name, data, file_type, expected in variants:
            started = time.perf_counter()
            pages = extract(data, file_type)
            elapsed = time.perf_counter() - started
            actual = " ".join(p.text for p in pages)
            cer = Levenshtein.distance(_norm(expected), _norm(actual)) / len(_norm(expected))
            confidences = [p.ocr_confidence or 0.0 for p in pages if p.method == "ocr"]
            min_conf = min(confidences) if confidences else None
            conf_text = "—" if min_conf is None else f"{min_conf:.0f}"
            print(f"| {doc.slug} | {name} | {cer:.1%} | {conf_text} | {elapsed:.1f}s |")
            if name in ("digital", "docx") and cer > 0:
                failures.append(f"{doc.slug}/{name}: text not extracted exactly")
            elif name in ("scan good", "scan poor", "photo") and cer > MAX_CER:
                failures.append(f"{doc.slug}/{name}: error rate {cer:.1%} > {MAX_CER:.0%}")
            elif name == "scan bad" and (min_conf is None or min_conf >= LOW_OCR_CONFIDENCE):
                failures.append(f"{doc.slug}/{name}: unreadable scan not flagged")
    print()
    if failures:
        print("**Failures:**\n")
        for f in failures:
            print(f"- {f}")
        return 1
    print(
        f"All checks passed (normal scans ≤ {MAX_CER:.0%} errors; unreadable scans flagged "
        f"below {LOW_OCR_CONFIDENCE:.0f}% confidence)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
