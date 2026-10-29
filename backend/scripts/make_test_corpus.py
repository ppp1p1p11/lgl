"""Write the synthetic test documents to a folder, to try uploads by hand.

Usage (from backend/): uv run python scripts/make_test_corpus.py ../test-documents
All content is fictional (ADR-0007).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.corpus.generator import (
    build_corpus,
    render_docx,
    render_pdf,
    render_photo,
    render_scan,
)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "test-documents")
    out.mkdir(parents=True, exist_ok=True)
    for doc in build_corpus():
        (out / f"{doc.slug}.pdf").write_bytes(render_pdf(doc))
        (out / f"{doc.slug}-escaneado.pdf").write_bytes(render_scan(doc, "poor"))
        (out / f"{doc.slug}-ilegivel.pdf").write_bytes(render_scan(doc, "bad"))
        (out / f"{doc.slug}-foto.jpg").write_bytes(render_photo(doc))
        (out / f"{doc.slug}.docx").write_bytes(render_docx(doc))
    print(f"Wrote {len(list(out.iterdir()))} files to {out}")


if __name__ == "__main__":
    main()
