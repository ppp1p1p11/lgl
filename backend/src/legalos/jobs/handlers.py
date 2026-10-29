"""Job handlers. Each phase registers its own (OCR, embeddings, summaries…)."""

# Importing a module registers its handlers.
from sqlalchemy.orm import Session

import legalos.documents.service  # noqa: F401
from legalos.audit.service import record
from legalos.jobs.models import Job
from legalos.jobs.queue import handler


@handler("system.ping")
def ping(db: Session, job: Job) -> None:
    """A no-op job used to check that the worker runs jobs in the right firm context."""
    record(
        db,
        "system.ping",
        tenant_id=job.tenant_id,
        actor_user_id=job.enqueued_by,
        entity_type="job",
        entity_id=str(job.id),
    )
