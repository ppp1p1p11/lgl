"""Load legal texts into the corpus. Runs as the owner role (the app can only read).

Re-runnable: a unit whose text did not change is left alone; a changed unit gets a new
version and the previous one is closed (temporal validity, brief rule 4). Every version
stores where and when its text was retrieved, and a content hash.

Usage (from backend/):
    uv run python -m legalos.corpus.ingest path/to/file.txt [more files…]
    uv run python -m legalos.corpus.ingest --demo      # demo sample, never in production
"""

import hashlib
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from legalos.config import get_settings
from legalos.corpus.models import IngestionRun, LegalDocument, LegalUnit, LegalUnitVersion
from legalos.corpus.parser import ParsedDocument, parse

DEMO_DIR = Path(__file__).resolve().parent / "demo"


def ingest_text(db: Session, source: str, *, source_name: str) -> dict[str, int]:
    parsed = parse(source)
    run = IngestionRun(source=source_name[:300])
    db.add(run)
    db.flush()
    stats = _apply(db, parsed, run)
    run.status, run.stats, run.finished_at = "succeeded", stats, datetime.now(UTC)
    db.flush()
    return stats


def _apply(db: Session, parsed: ParsedDocument, run: IngestionRun) -> dict[str, int]:
    meta = parsed.meta
    document = db.scalar(
        select(LegalDocument).where(LegalDocument.identifier == meta["identifier"])
    )
    if document is None:
        document = LegalDocument(identifier=meta["identifier"])
        db.add(document)
    document.doc_type = meta["doc_type"]
    document.short_name = meta["short_name"]
    document.title = meta["title"]
    document.issuing_body = meta.get("issuing_body")
    document.urn = meta.get("urn")
    document.source_url = meta.get("source_url")
    document.review_status = meta.get("review_status", "oficial")
    if meta.get("publication_date"):
        document.publication_date = date.fromisoformat(meta["publication_date"])
    db.flush()

    retrieved_at = (
        datetime.fromisoformat(meta["retrieved_at"].replace("Z", "+00:00"))
        if meta.get("retrieved_at")
        else None
    )
    valid_from = date.fromisoformat(meta["valid_from"]) if meta.get("valid_from") else None
    existing = {
        u.label: u
        for u in db.scalars(select(LegalUnit).where(LegalUnit.legal_document_id == document.id))
    }
    stats = {"units": len(parsed.units), "new": 0, "changed": 0, "unchanged": 0}
    by_label: dict[str, LegalUnit] = {}
    for position, item in enumerate(parsed.units):
        unit = existing.get(item.label)
        if unit is None:
            unit = LegalUnit(legal_document_id=document.id, label=item.label)
            db.add(unit)
        unit.unit_type = item.unit_type
        unit.heading_path = item.heading_path
        unit.position = position
        unit.parent_id = by_label[item.parent_label].id if item.parent_label else None
        db.flush()
        by_label[item.label] = unit

        digest = hashlib.sha256(item.text.encode()).hexdigest()
        current = db.scalar(
            select(LegalUnitVersion)
            .where(LegalUnitVersion.legal_unit_id == unit.id, LegalUnitVersion.valid_to.is_(None))
            .order_by(LegalUnitVersion.created_at.desc())
            .limit(1)
        )
        if current is not None and current.content_hash == digest:
            stats["unchanged"] += 1
            continue
        if current is not None:
            # Close the previous text: it stays searchable "as of" earlier dates.
            current.valid_to = valid_from or datetime.now(UTC).date()
            if current.status == "vigente":
                current.status = "alterado"
            stats["changed"] += 1
        else:
            stats["new"] += 1
        db.add(
            LegalUnitVersion(
                legal_unit_id=unit.id,
                text=item.text,
                valid_from=valid_from if current else None,
                status=item.status,
                amendment_note=item.amendment_note,
                content_hash=digest,
                source_url=document.source_url,
                retrieved_at=retrieved_at,
                ingestion_run_id=run.id,
            )
        )
        db.flush()
    return stats


def ingest_demo(db: Session) -> dict[str, dict[str, int]]:
    return {
        path.name: ingest_text(db, path.read_text(encoding="utf-8"), source_name=path.name)
        for path in sorted(DEMO_DIR.glob("*.txt"))
    }


def main() -> None:
    args = sys.argv[1:]
    settings = get_settings()
    if not args:
        sys.exit(__doc__)
    if args == ["--demo"] and settings.environment == "production":
        sys.exit("Refusing to load the unverified demo corpus in production.")
    engine = create_engine(settings.database_owner_url.get_secret_value())
    with Session(engine) as db, db.begin():
        if args == ["--demo"]:
            results = ingest_demo(db)
        else:
            results = {
                name: ingest_text(db, Path(name).read_text(encoding="utf-8"), source_name=name)
                for name in args
            }
    engine.dispose()
    for name, stats in results.items():
        print(f"{name}: {stats}")


if __name__ == "__main__":
    main()
