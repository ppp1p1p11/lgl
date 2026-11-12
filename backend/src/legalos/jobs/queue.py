"""Postgres-backed job queue (ADR-0004).

Enqueue inside the same transaction as the data change, so a job never exists for data
that was rolled back. Workers claim jobs with `FOR UPDATE SKIP LOCKED` (in the
`jobs_claim` database function) and run each one inside its firm's tenant context.
"""

import logging
import traceback
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from legalos.core.db import get_sessionmaker, set_db_context
from legalos.jobs.models import Job

logger = logging.getLogger(__name__)

JobHandler = Callable[[Session, Job], None]
_HANDLERS: dict[str, JobHandler] = {}

LEASE_SECONDS = 15 * 60


def handler(kind: str) -> Callable[[JobHandler], JobHandler]:
    """Register a function as the handler for a job kind."""

    def register(fn: JobHandler) -> JobHandler:
        if kind in _HANDLERS:
            raise ValueError(f"Duplicate job handler: {kind}")
        _HANDLERS[kind] = fn
        return fn

    return register


def enqueue(
    db: Session,
    kind: str,
    *,
    tenant_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
    enqueued_by: uuid.UUID | None = None,
    max_attempts: int = 5,
) -> Job:
    job = Job(
        tenant_id=tenant_id,
        kind=kind,
        payload=payload or {},
        enqueued_by=enqueued_by,
        max_attempts=max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def retry_delay_seconds(attempts: int) -> int:
    """Exponential backoff: 30s, 1min, 2min, 4min… capped at 1 hour."""
    return int(min(30 * 2 ** max(attempts - 1, 0), 3600))


def run_one(worker_id: str) -> bool:
    """Claim and run a single job. Returns False if there was nothing to do."""
    sessionmaker = get_sessionmaker()
    with sessionmaker() as db, db.begin():
        row = (
            db.execute(
                text("SELECT * FROM jobs_claim(:worker, :lease)"),
                {"worker": worker_id, "lease": LEASE_SECONDS},
            )
            .mappings()
            .first()
        )
    if row is None:
        return False
    job = Job(**dict(row))

    error: str | None = None
    try:
        fn = _HANDLERS.get(job.kind)
        if fn is None:
            raise LookupError(f"No handler registered for job kind {job.kind!r}")
        with sessionmaker() as db, db.begin():
            set_db_context(db, user_id=job.enqueued_by, tenant_id=job.tenant_id)
            fn(db, job)
    except Exception as exc:
        # Only the exception type and traceback are stored: never document contents.
        error = "".join(traceback.format_exception_only(exc)).strip()[:2000]
        logger.warning(
            "job failed",
            extra={"job_id": str(job.id), "kind": job.kind, "attempt": job.attempts},
        )

    with sessionmaker() as db, db.begin():
        db.execute(
            text("SELECT jobs_finish(:id, :worker, :error, :delay)"),
            {
                "id": job.id,
                "worker": worker_id,
                "error": error,
                "delay": retry_delay_seconds(job.attempts),
            },
        )
    return True
