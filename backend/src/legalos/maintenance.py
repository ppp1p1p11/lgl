"""Housekeeping, run periodically (e.g. hourly by a scheduler) as the owner role.

Usage: python -m legalos.maintenance

- Uploads that were started but never completed are removed after 24 hours, together
  with any partial object in storage.
- Expired and revoked login sessions and old throttling records are deleted.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session

from legalos import all_models  # noqa: F401  (resolves foreign keys between models)
from legalos.auth.models import AuthAttempt
from legalos.config import get_settings
from legalos.documents.models import Document, DocumentVersion
from legalos.storage import files

STALE_UPLOAD_AFTER = timedelta(hours=24)


def cleanup(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    stats = {"stale_uploads": 0, "empty_documents": 0, "sessions": 0, "auth_attempts": 0}
    stale = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.status == "pending_upload",
            DocumentVersion.created_at < now - STALE_UPLOAD_AFTER,
        )
    ).all()
    for version in stale:
        files.delete_object(version.tenant_id, version.storage_key)
        db.delete(version)
        stats["stale_uploads"] += 1
    db.flush()
    # Documents left without any version (their only upload was abandoned).
    empty = db.scalars(
        select(Document).where(
            ~select(DocumentVersion.id).where(DocumentVersion.document_id == Document.id).exists(),
            Document.created_at < now - STALE_UPLOAD_AFTER,
        )
    ).all()
    for document in empty:
        db.delete(document)
        stats["empty_documents"] += 1
    cutoff = now - timedelta(days=1)
    stats["sessions"] = len(
        db.execute(
            text(
                "DELETE FROM sessions WHERE expires_at < :cutoff OR revoked_at < :cutoff"
                " RETURNING id"
            ),
            {"cutoff": cutoff},
        ).all()
    )
    stats["auth_attempts"] = len(
        db.execute(
            delete(AuthAttempt)
            .where(AuthAttempt.attempted_at < now - timedelta(days=7))
            .returning(AuthAttempt.id)
        ).all()
    )
    return stats


def main() -> None:
    engine = create_engine(get_settings().database_owner_url.get_secret_value())
    with Session(engine) as db, db.begin():
        stats = cleanup(db)
    engine.dispose()
    print(f"Maintenance done: {stats}")


if __name__ == "__main__":
    main()
